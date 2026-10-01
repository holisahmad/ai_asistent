"""LLM adapter (Fase 6) — provider dapat diganti.

- `local`: stub deterministik untuk dev/test — merangkum potongan konteks
  terpilih dan menyebut nomor sitasi, tanpa API eksternal.
- `openai`: chat completion (butuh APP_OPENAI_API_KEY).

Prompt grounded (roadmap): jawab HANYA dari konteks; bedakan fakta
(bersitasi), inferensi, dan ketidakpastian; jika konteks tidak cukup,
jawab persis `NO_ANSWER` — backend mengubahnya menjadi pesan
"informasi belum tersedia" (no-answer behavior wajib).
"""

import re
from dataclasses import dataclass
from typing import Protocol

from ai_asistent_core.config import get_settings

NO_ANSWER = "NO_ANSWER"

_SYSTEM_PROMPT = """Kamu asisten knowledge base perusahaan. ATURAN WAJIB:
1. Jawab HANYA dari potongan konteks yang diberikan. Jangan gunakan pengetahuan luar.
2. Sertakan nomor sitasi [1], [2] untuk setiap klaim yang berasal dari konteks.
3. Bedakan dengan jelas: fakta dari sumber (bersitasi), inferensimu (tandai "Inferensi:"),
   dan hal yang tidak pasti (tandai "Tidak pasti:").
4. Jika konteks TIDAK cukup untuk menjawab pertanyaan, jawab persis: NO_ANSWER
   (tanpa teks lain).
5. Jangan pernah mengarang nama file, angka, atau fakta yang tidak ada di konteks."""


@dataclass(frozen=True)
class LLMResult:
    """Hasil generation: teks jawaban + flag apakah model menyatakan tak cukup bukti."""

    text: str
    no_answer: bool


class LLMProvider(Protocol):
    """Kontrak provider LLM."""

    def generate(self, question: str, contexts: list[str]) -> LLMResult: ...


def _context_block(contexts: list[str]) -> str:
    return "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts))


def _is_no_answer(text: str) -> bool:
    """Deteksi no-answer (toleran format: dengan/tanpa tanda baca)."""
    return bool(re.search(r"\bNO[_ ]?ANSWER\b", text.strip(), flags=re.IGNORECASE))


class LocalStubLLM:
    """LLM deterministik untuk dev/test: rangkum potongan konteks terpilih.

    Aturan grounded disimulasikan: potongan pertama yang memuat token dari
    pertanyaan dijadikan inti jawaban; jika tak ada yang cocok → NO_ANSWER.
    """

    def generate(self, question: str, contexts: list[str]) -> LLMResult:
        if not contexts:
            return LLMResult(text=NO_ANSWER, no_answer=True)
        q_tokens = {t.lower() for t in re.findall(r"[a-z0-9]+", question.lower()) if len(t) >= 3}
        best_idx: int | None = None
        for i, ctx in enumerate(contexts):
            lowered = ctx.lower()
            if any(t in lowered for t in q_tokens):
                best_idx = i
                break
        if best_idx is None:
            return LLMResult(text=NO_ANSWER, no_answer=True)
        excerpt = contexts[best_idx].strip().replace("\n", " ")
        if len(excerpt) > 400:
            excerpt = excerpt[:400].rstrip() + "…"
        return LLMResult(
            text=f"Berdasarkan dokumen internal [{best_idx + 1}]: {excerpt}",
            no_answer=False,
        )


class OpenAILLM:
    """Chat completion via OpenAI API."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("pip install openai untuk provider openai") from exc
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, question: str, contexts: list[str]) -> LLMResult:
        user_content = (
            f"Konteks dari knowledge base:\n\n{_context_block(contexts)}\n\n"
            f"Pertanyaan: {question}"
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
        return LLMResult(text=text, no_answer=_is_no_answer(text))


def get_llm_provider() -> LLMProvider:
    """Pilih provider dari settings (llm_provider: local|openai)."""
    s = get_settings()
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("APP_OPENAI_API_KEY belum diset")
        return OpenAILLM(s.openai_api_key, s.openai_chat_model)
    return LocalStubLLM()


def build_grounded_prompt(question: str, contexts: list[str]) -> list[dict[str, str]]:
    """Prompt siap kirim (diekspos untuk pengujian & provider lain)."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Konteks dari knowledge base:\n\n{_context_block(contexts)}\n\n"
                f"Pertanyaan: {question}"
            ),
        },
    ]
