"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type Chat,
  type ChatStreamEvent,
  type Citation,
  type Message,
  downloadUrl,
  getChat,
  listChats,
  sendFeedback,
  streamChat,
} from "@/lib/api";
import Markdown from "./Markdown";

type Props = { workspaceId: string };

type Pending = { streaming: string; abort: AbortController | null };

function KindBadge({ kind }: { kind: string | null }) {
  if (!kind || kind === "grounded" || kind === "extractive") return null;
  if (kind === "no_answer") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-amber-400/70">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400/70" />
        Tidak ditemukan di knowledge base
      </span>
    );
  }
  if (kind === "grounded_web") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-fuchsia-400/70">
        <span className="h-1.5 w-1.5 rounded-full bg-fuchsia-400/70" />
        Sumber web
      </span>
    );
  }
  return null;
}

function CitationChip({
  citation,
  workspaceId,
  onSelect,
}: {
  citation: Citation;
  workspaceId: string;
  onSelect: (c: Citation) => void;
}) {
  const isWeb = citation.source_type === "web";
  // Nama file pendek tanpa extension
  const shortName = isWeb
    ? (citation.url ? new URL(citation.url).hostname : "web")
    : citation.filename.replace(/\.[^.]+$/, "").slice(0, 28);

  return (
    <button
      onClick={() => onSelect(citation)}
      title={isWeb ? citation.url ?? citation.filename : citation.filename}
      className={`inline-flex max-w-[14rem] items-center gap-1 truncate rounded-md px-2 py-0.5 text-xs transition ${
        isWeb
          ? "bg-fuchsia-500/10 text-fuchsia-300 hover:bg-fuchsia-500/20"
          : "bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
      }`}
    >
      <span className="shrink-0 text-slate-500">[{citation.idx}]</span>
      <span className="truncate">{shortName}</span>
    </button>
  );
}

export default function ChatPanel({ workspaceId }: Props) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [question, setQuestion] = useState("");
  const [allowWeb, setAllowWeb] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const refreshChats = useCallback(async () => {
    try {
      setChats(await listChats(workspaceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memuat chat");
    }
  }, [workspaceId]);

  useEffect(() => {
    setActiveChatId(null);
    setMessages([]);
    setPending(null);
    setSelectedCitation(null);
    void refreshChats();
  }, [workspaceId, refreshChats]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pending?.streaming]);

  async function openChat(chatId: string) {
    setError(null);
    setLoading(true);
    setSelectedCitation(null);
    try {
      const detail = await getChat(workspaceId, chatId);
      setActiveChatId(chatId);
      setMessages(detail.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal membuka chat");
    } finally {
      setLoading(false);
    }
  }

  async function copyMessage(m: Message) {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopiedId(m.id);
      window.setTimeout(() => setCopiedId(null), 1500);
    } catch {
      setError("Gagal menyalin ke clipboard (izin browser).");
    }
  }

  async function rate(m: Message, value: "up" | "down") {
    if (!activeChatId) return;
    const next = m.feedback === value ? null : value;
    try {
      const updated = await sendFeedback(workspaceId, activeChatId, m.id, next);
      setMessages((prev) =>
        prev.map((x) => (x.id === m.id ? { ...x, feedback: updated.feedback } : x))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal mengirim umpan balik");
    }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = question.trim();
    if (!text || pending) return;
    setLastQuestion(text);

    const abort = new AbortController();
    setError(null);
    setQuestion("");
    setSelectedCitation(null);
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`,
        role: "user",
        content: text,
        answer_kind: null,
        feedback: null,
        citations: [],
        created_at: new Date().toISOString(),
      },
    ]);
    setPending({ streaming: "", abort });

    try {
      await streamChat(
        workspaceId,
        { question: text, chatId: activeChatId, allowWeb },
        (ev: ChatStreamEvent) => {
          if (ev.type === "meta") {
            setActiveChatId(ev.chatId);
          } else if (ev.type === "delta") {
            setPending((p) => (p ? { ...p, streaming: p.streaming + ev.text } : p));
          } else if (ev.type === "done") {
            setMessages((prev) => [
              ...prev,
              {
                id: ev.messageId,
                role: "assistant",
                content: ev.text,
                answer_kind: ev.answerKind,
                feedback: null,
                citations: ev.citations,
                created_at: new Date().toISOString(),
              },
            ]);
            setPending(null);
          } else if (ev.type === "error") {
            setError(`Gagal menjawab: ${ev.message}`);
            setPending(null);
          }
        },
        abort.signal
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(
          err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Gagal mengirim"
        );
      }
      setPending(null);
    } finally {
      setPending((p) => (p && p.abort === abort ? null : p));
      void refreshChats();
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
      {/* Daftar chat */}
      <aside className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-300">Riwayat chat</h3>
          <button
            onClick={() => {
              setActiveChatId(null);
              setMessages([]);
              setSelectedCitation(null);
            }}
            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
          >
            + Baru
          </button>
        </div>
        <ul className="mt-3 space-y-1">
          {chats.length === 0 && (
            <li className="px-1 py-2 text-xs text-slate-500">Belum ada chat.</li>
          )}
          {chats.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => void openChat(c.id)}
                className={`w-full truncate rounded-md px-2 py-1.5 text-left text-sm transition ${
                  activeChatId === c.id
                    ? "bg-sky-500/15 text-sky-200"
                    : "text-slate-400 hover:bg-slate-800"
                }`}
              >
                {c.title}
                <span className="ml-1 text-xs text-slate-500">({c.message_count})</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Area chat */}
      <section className="flex min-h-[32rem] flex-col rounded-xl border border-slate-800 bg-slate-900/40">
        <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
          {loading && <p className="text-sm text-slate-500">Memuat…</p>}
          {!loading && messages.length === 0 && !pending && (
            <div className="rounded-lg border border-dashed border-slate-700 p-6 text-center">
              <p className="text-slate-300">Tanya apa pun tentang dokumen workspace ini.</p>
              <p className="mt-1 text-sm text-slate-500">
                Jawaban hanya dari knowledge base internal; aktifkan “izinkan web” bila
                bukti internal tidak cukup.
              </p>
            </div>
          )}

          {messages.map((m) => (
            <article
              key={m.id}
              className={m.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[88%] rounded-2xl px-4 py-3 ${
                  m.role === "user"
                    ? "bg-sky-500/20 text-slate-100"
                    : "bg-slate-800/60 text-slate-100"
                }`}
              >
                {m.role === "assistant" && (
                  <div className="mb-2.5 flex items-center justify-between gap-3">
                    <KindBadge kind={m.answer_kind} />
                    <div className="ml-auto flex items-center gap-1">
                      <button
                        onClick={() => void copyMessage(m)}
                        title="Salin jawaban"
                        aria-label="Salin jawaban"
                        className="rounded px-1.5 py-0.5 text-xs text-slate-500 hover:text-slate-300 transition"
                      >
                        {copiedId === m.id ? "✓ Tersalin" : "Salin"}
                      </button>
                      <button
                        onClick={() => void rate(m, "up")}
                        title="Jawaban membantu"
                        aria-label="Jawaban membantu"
                        aria-pressed={m.feedback === "up"}
                        className={`rounded px-1 py-0.5 text-sm transition ${
                          m.feedback === "up"
                            ? "text-emerald-400"
                            : "text-slate-600 hover:text-slate-300"
                        }`}
                      >
                        👍
                      </button>
                      <button
                        onClick={() => void rate(m, "down")}
                        title="Jawaban kurang tepat"
                        aria-label="Jawaban kurang tepat"
                        aria-pressed={m.feedback === "down"}
                        className={`rounded px-1 py-0.5 text-sm transition ${
                          m.feedback === "down"
                            ? "text-red-400"
                            : "text-slate-600 hover:text-slate-300"
                        }`}
                      >
                        👎
                      </button>
                    </div>
                  </div>
                )}
                {m.role === "assistant" ? (
                  <Markdown
                    content={m.content}
                    onCitation={(idx) => {
                      const cit = m.citations.find((c) => c.idx === idx);
                      if (cit) setSelectedCitation(cit);
                    }}
                  />
                ) : (
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>
                )}
                {/* Sitasi — deduplicate berdasarkan file_id + filename */}
                {m.citations.length > 0 && (() => {
                  const seen = new Set<string>();
                  const unique = m.citations.filter((c) => {
                    const key = c.source_type === "web" ? (c.url ?? c.filename) : (c.file_id ?? c.filename);
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                  });
                  return (
                    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-slate-700/50 pt-2.5">
                      {unique.map((c) => (
                        <CitationChip
                          key={`${m.id}-${c.idx}`}
                          citation={c}
                          workspaceId={workspaceId}
                          onSelect={setSelectedCitation}
                        />
                      ))}
                    </div>
                  );
                })()}
              </div>
            </article>
          ))}

          {pending && (
            <article className="flex justify-start">
              <div className="max-w-[88%] rounded-2xl bg-slate-800/60 px-4 py-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex gap-0.5">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:0ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:150ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:300ms]" />
                  </span>
                </div>
                {pending.streaming ? (
                  <Markdown content={pending.streaming} />
                ) : (
                  <p className="text-sm text-slate-500">Mencari di knowledge base…</p>
                )}
              </div>
            </article>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Panel detail sitasi */}
        {selectedCitation && (
          <div className="border-t border-slate-800 bg-slate-950/60 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-white">
                  [{selectedCitation.idx}] {selectedCitation.filename}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {selectedCitation.source_type === "web"
                    ? "sumber eksternal (web)"
                    : `internal · ${selectedCitation.locator_type} ${selectedCitation.locator_start}`}
                  {selectedCitation.score > 0 && ` · skor ${selectedCitation.score.toFixed(3)}`}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {selectedCitation.source_type === "web" && selectedCitation.url && (
                  <a
                    href={selectedCitation.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="rounded-md border border-fuchsia-500/40 px-2 py-1 text-xs text-fuchsia-300 hover:bg-fuchsia-500/10"
                  >
                    Buka sumber
                  </a>
                )}
                {selectedCitation.source_type === "internal" && selectedCitation.file_id && (
                  <a
                    href={downloadUrl(workspaceId, selectedCitation.file_id)}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                  >
                    Unduh file
                  </a>
                )}
                <button
                  onClick={() => setSelectedCitation(null)}
                  className="rounded-md px-2 py-1 text-xs text-slate-400 hover:text-slate-200"
                >
                  Tutup
                </button>
              </div>
            </div>
            <p className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap text-sm text-slate-300">
              {selectedCitation.snippet}
            </p>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="flex items-center justify-between gap-3 border-t border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300"
          >
            <span>{error}</span>
            {lastQuestion && (
              <button
                onClick={() => {
                  setError(null);
                  setQuestion(lastQuestion);
                }}
                className="rounded-md border border-red-500/40 px-2 py-1 text-xs text-red-200 hover:bg-red-500/10"
              >
                Coba lagi
              </button>
            )}
          </div>
        )}

        <form onSubmit={send} className="border-t border-slate-800 p-3">
          <div className="flex items-end gap-2">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(e);
                }
              }}
              rows={2}
              placeholder="Tulis pertanyaan… (Enter kirim, Shift+Enter baris baru)"
              className="flex-1 resize-none rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            />
            {pending ? (
              <button
                type="button"
                onClick={() => pending.abort?.abort()}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!question.trim()}
                className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-400 disabled:opacity-50"
              >
                Kirim
              </button>
            )}
          </div>
          <label className="mt-2 flex items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={allowWeb}
              onChange={(e) => setAllowWeb(e.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-900"
            />
            Izinkan pencarian web bila knowledge base internal tidak cukup
            (sumber eksternal selalu ditandai)
          </label>
        </form>
      </section>
    </div>
  );
}
