"""Chat endpoints — Fase 6: RAG grounded streaming + riwayat chat.

- POST /chat/stream: SSE. Retrieve hybrid (ACL workspace) → LLM grounded →
  jawaban + citations. Peristiwa: `meta`, `delta`, `done`. No-answer →
  "Informasi belum tersedia…" + answer_kind=no_answer.
- GET /chats, GET /chats/{chat_id}: riwayat (viewer+).

RBAC: viewer+ (chat = baca knowledge base). Non-anggota workspace → 404.
"""

import json
from collections.abc import Iterator

from ai_asistent_core.models import Chat, Citation, Message, utcnow
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit as audit_mod
from app.deps import CurrentUser, DbSession, audit, require_role
from app.schemas import (
    ChatCreateIn,
    ChatDetailOut,
    ChatOut,
    CitationOut,
    MessageOut,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["chat"])

NO_ANSWER_MESSAGE = "Informasi belum tersedia dalam knowledge base."


def _get_chat_or_404(db: Session, workspace_id: str, chat_id: str) -> Chat:
    chat = db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    return chat


def _message_out(db: Session, m: Message) -> MessageOut:
    cits = db.execute(
        select(Citation).where(Citation.message_id == m.id).order_by(Citation.idx)
    ).scalars().all()
    return MessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        answer_kind=m.answer_kind,
        citations=[
            CitationOut(
                idx=c.idx,
                chunk_id=c.chunk_id,
                file_id=c.file_id,
                filename=c.filename,
                locator_type=c.locator_type,
                locator_start=c.locator_start,
                locator_end=c.locator_end,
                snippet=c.snippet,
                score=c.score,
            )
            for c in cits
        ],
        created_at=m.created_at,
    )


@router.post("/chat/stream")
def chat_stream(
    workspace_id: str,
    payload: ChatCreateIn,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("viewer")),
) -> StreamingResponse:
    """SSE: bertanya ke knowledge base (viewer+). Sitasi di event `done`."""

    # Tulis pesan user & resolve chat SEKARANG (dalam request, sebelum
    # generator jalan) agar validasi & ownership jelas sebelum streaming.
    if payload.chat_id is not None:
        chat = _get_chat_or_404(db, workspace_id, payload.chat_id)
    else:
        chat = Chat(
            workspace_id=workspace_id,
            user_id=current.id,
            title=payload.question[:100],
        )
        db.add(chat)
        db.flush()

    user_msg = Message(chat_id=chat.id, role="user", content=payload.question)
    db.add(user_msg)
    audit(
        db,
        action="chat.ask",
        workspace_id=workspace_id,
        user_id=current.id,
        target=chat.id,
        meta={"question_chars": len(payload.question)},
    )
    audit_mod.write_audit_log(
        {
            "action": "chat.ask",
            "workspace_id": workspace_id,
            "user_id": current.id,
            "target": chat.id,
        }
    )
    db.commit()
    chat_id = chat.id

    def _event(name: str, data: dict[str, object]) -> str:
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate() -> Iterator[str]:
        from ai_asistent_core.rag import answer_question

        yield _event("meta", {"chat_id": chat_id})
        try:
            answer = answer_question(db, workspace_id, payload.question)
        except Exception as exc:  # noqa: BLE001 - error tetap jadi event SSE
            db.rollback()
            yield _event("error", {"message": f"RAG failed: {type(exc).__name__}"})
            return

        assistant = Message(
            chat_id=chat_id,
            role="assistant",
            content=answer.text,
            answer_kind=answer.answer_kind,
            answer_meta_json=answer.meta_json,
        )
        db.add(assistant)
        db.flush()
        for cit in answer.citations:
            db.add(
                Citation(
                    message_id=assistant.id,
                    idx=cit.idx,
                    chunk_id=cit.chunk_id,
                    file_id=cit.file_id,
                    filename=cit.filename,
                    locator_type=cit.locator_type,
                    locator_start=cit.locator_start,
                    locator_end=cit.locator_end,
                    snippet=cit.snippet,
                    score=cit.score,
                )
            )
        chat.updated_at = utcnow()
        db.commit()

        # Streaming kata-per-kata (simulasi token stream; adapter local
        # deterministik — OpenAI bisa dipasang token-asli di sini nanti).
        for word in answer.text.split(" "):
            yield _event("delta", {"text": word + " "})
        yield _event(
            "done",
            {
                "message_id": assistant.id,
                "answer_kind": answer.answer_kind,
                "citations": [
                    {
                        "idx": c.idx,
                        "chunk_id": c.chunk_id,
                        "file_id": c.file_id,
                        "filename": c.filename,
                        "locator_type": c.locator_type,
                        "locator_start": c.locator_start,
                        "locator_end": c.locator_end,
                        "snippet": c.snippet,
                        "score": c.score,
                    }
                    for c in answer.citations
                ],
            },
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chats", response_model=list[ChatOut])
def list_chats(
    workspace_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("viewer")),
) -> list[ChatOut]:
    """Daftar chat workspace terbaru lebih dulu (viewer+)."""
    counts = dict(
        db.execute(
            select(Message.chat_id, func.count(Message.id)).group_by(Message.chat_id)
        ).all()
    )
    rows = db.execute(
        select(Chat)
        .where(Chat.workspace_id == workspace_id)
        .order_by(Chat.created_at.desc())
    ).scalars().all()
    return [
        ChatOut(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            message_count=int(counts.get(c.id, 0)),
        )
        for c in rows
    ]


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
def get_chat(
    workspace_id: str,
    chat_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("viewer")),
) -> ChatDetailOut:
    """Detail chat + seluruh pesan + sitasi (viewer+)."""
    chat = _get_chat_or_404(db, workspace_id, chat_id)
    messages = db.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    ).scalars().all()
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        created_at=chat.created_at,
        message_count=len(messages),
        messages=[_message_out(db, m) for m in messages],
    )
