"""LLM adapter (Fase 6/7) — provider dapat diganti.

- `local`: stub deterministik untuk dev/test — merangkum potongan konteks
  terpilih dan menyebut nomor sitasi, tanpa API eksternal.
- `openai`: SDK resmi OpenAI (api.openai.com; butuh APP_OPENAI_API_KEY).
- `openai_compat`: endpoint OpenAI-compatible apa pun (vLLM, Combo, gateway
  lokal) via httpx — set APP_OPENAI_BASE_URL, APP_OPENAI_API_KEY,
  APP_OPENAI_CHAT_MODEL. Parsing toleran: body JSON utuh atau SSE.

Prompt grounded (roadmap): jawab HANYA dari konteks; bedakan fakta
(bersitasi), inferensi, dan ketidakpastian; jika konteks tidak cukup,
jawab persis `NO_ANSWER` — backend mengubahnya menjadi pesan
"informasi belum tersedia" (no-answer behavior wajib).
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

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

    def stream_generate(self, question: str, contexts: list[str]) -> Iterator[str]: ...


def _context_block(contexts: list[str]) -> str:
    return "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts))


def _is_no_answer(text: str) -> bool:
    """Deteksi no-answer (toleran format: dengan/tanpa tanda baca)."""
    return bool(re.search(r"\bNO[_ ]?ANSWER\b", text.strip(), flags=re.IGNORECASE))


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

    def stream_generate(self, question: str, contexts: list[str]) -> Iterator[str]:
        """Simulasi token stream: kata per kata dari jawaban generate()."""
        for word in self.generate(question, contexts).text.split(" "):
            yield word + " "


class OpenAILLM:
    """Chat completion via OpenAI SDK resmi."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("pip install openai untuk provider openai") from exc
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, question: str, contexts: list[str]) -> LLMResult:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=build_grounded_prompt(question, contexts),
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
        return LLMResult(text=text, no_answer=_is_no_answer(text))

    def stream_generate(self, question: str, contexts: list[str]) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=build_grounded_prompt(question, contexts),
            temperature=0.0,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


def _extract_content(body: str) -> str:
    """Ekstrak konten dari respons chat completion non-stream, toleran.

    Gateway OpenAI-compatible kadang mengembalikan JSON utuh, kadang
    body SSE (baris `data: {...}` — termasuk jejak `data: [DONE]` di
    akhir body JSON, sebagaimana gateway Combo lokal).
    """
    body = body.strip()
    try:
        obj: dict[str, Any] = json.loads(body)
        content = obj["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    # SSE atau JSON+jejak SSE: kumpulkan delta.content dari tiap baris data:
    parts: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
            delta = obj["choices"][0].get("delta", {}).get("content")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            continue
        if isinstance(delta, str) and delta:
            parts.append(delta)
    if parts:
        return "".join(parts)
    # Terakhir: coba ekstrak "content":"..." mentah (body campur/aneh).
    m = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
    if m:
        try:
            return str(json.loads(f'"{m.group(1)}"'))
        except json.JSONDecodeError:  # pragma: no cover - fallback mentah
            return m.group(1)
    return ""


class OpenAICompatLLM:
    """LLM via endpoint OpenAI-compatible generik (httpx, tanpa SDK)."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _payload(self, question: str, contexts: list[str]) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": build_grounded_prompt(question, contexts),
            "temperature": 0.0,
        }

    def generate(self, question: str, contexts: list[str]) -> LLMResult:
        resp = httpx.post(
            f"{self._base_url}/chat/completions",
            json=self._payload(question, contexts),
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        text = _extract_content(resp.text).strip()
        return LLMResult(text=text, no_answer=_is_no_answer(text))

    def stream_generate(self, question: str, contexts: list[str]) -> Iterator[str]:
        """SSE stream asli; fallback ke non-stream bila endpoint tak streaming."""
        payload = dict(self._payload(question, contexts), stream=True)
        emitted = False
        try:
            with httpx.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            break
                        continue
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta", {}).get("content")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
                    if isinstance(delta, str) and delta:
                        emitted = True
                        yield delta
        except httpx.HTTPError:
            emitted = False  # fallback di bawah
        if not emitted:
            yield self.generate(question, contexts).text


def get_llm_provider() -> LLMProvider:
    """Pilih provider dari settings (llm_provider: local|openai|openai_compat)."""
    s = get_settings()
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("APP_OPENAI_API_KEY belum diset")
        return OpenAILLM(s.openai_api_key, s.openai_chat_model)
    if s.llm_provider == "openai_compat":
        if not s.openai_base_url:
            raise RuntimeError("APP_OPENAI_BASE_URL belum diset untuk openai_compat")
        return OpenAICompatLLM(
            s.openai_base_url,
            s.openai_api_key or "",
            s.openai_chat_model,
            s.openai_timeout_seconds,
        )
    return LocalStubLLM()
