"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type FileItem,
  deleteFile,
  downloadUrl,
  listFiles,
  reindexFile,
  uploadFile,
} from "@/lib/api";

type Props = { workspaceId: string; canContribute: boolean; canDelete: boolean };

const STATUS_STYLE: Record<string, string> = {
  queued: "bg-slate-500/15 text-slate-300",
  processing: "bg-amber-500/15 text-amber-300",
  indexed: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-red-500/15 text-red-300",
  deleted: "bg-slate-600/20 text-slate-400",
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FilesPanel({ workspaceId, canContribute, canDelete }: Props) {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      setFiles(await listFiles(workspaceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal memuat dokumen");
    }
  }, [workspaceId]);

  useEffect(() => {
    setFiles([]);
    setError(null);
    setNotice(null);
    void refresh();
  }, [workspaceId, refresh]);

  // Polling ringan selama ada file yang diproses worker.
  useEffect(() => {
    const pending = files.some((f) => f.status === "queued" || f.status === "processing");
    if (!pending) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [files, refresh]);

  async function handleUpload(files: FileList | File[]) {
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    const results: string[] = [];
    const errors: string[] = [];
    for (const file of fileArray) {
      try {
        const created = await uploadFile(workspaceId, file);
        results.push(created.filename);
      } catch (err) {
        const detail =
          err instanceof ApiError
            ? err.status === 409
              ? `${file.name}: isi file identik sudah ada.`
              : `${file.name}: ${err.detail}`
            : err instanceof Error
              ? `${file.name}: ${err.message}`
              : `${file.name}: upload gagal`;
        errors.push(detail);
      }
    }
    if (results.length > 0) {
      setNotice(
        results.length === 1
          ? `${results[0]} diunggah — sedang diproses.`
          : `${results.length} file diunggah — sedang diproses.`
      );
    }
    if (errors.length > 0) {
      setError(errors.join("\n"));
    }
    await refresh();
    setBusy(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function run(action: () => Promise<unknown>, okMessage: string) {
    setError(null);
    try {
      await action();
      setNotice(okMessage);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Aksi gagal");
    }
  }

  const accepted = ".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.html,.json";

  const visible = files.filter((f) => {
    const matchesQuery = f.filename.toLowerCase().includes(query.trim().toLowerCase());
    const matchesStatus = statusFilter === "all" || f.status === statusFilter;
    return matchesQuery && matchesStatus;
  });

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-white">Dokumen workspace</h2>
          <p className="text-sm text-slate-400">
            PDF, DOCX, PPTX, XLSX, TXT, MD, CSV, HTML, JSON · maks 50 MB
          </p>
        </div>
        {canContribute && (
          <label
            className={`cursor-pointer rounded-lg border px-3 py-2 text-sm transition ${
              busy
                ? "border-slate-700 text-slate-500"
                : "border-sky-500/60 text-sky-300 hover:bg-sky-500/10"
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept={accepted}
              multiple
              disabled={busy}
              className="hidden"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0)
                  void handleUpload(e.target.files);
              }}
            />
            {busy ? "Mengunggah…" : "Unggah dokumen"}
          </label>
        )}
      </div>

      {canContribute && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0)
              void handleUpload(e.dataTransfer.files);
          }}
          className={`mt-3 rounded-lg border border-dashed px-4 py-6 text-center text-sm transition ${
            dragging ? "border-sky-400 bg-sky-500/5 text-sky-200" : "border-slate-700 text-slate-400"
          }`}
        >
          Tarik & lepas satu atau beberapa file ke sini, atau klik “Unggah dokumen”.
        </div>
      )}

      {notice && (
        <p className="mt-3 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {files.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="doc-search">
            Cari dokumen
          </label>
          <input
            id="doc-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Cari nama dokumen…"
            className="min-w-[12rem] flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-sky-500"
          />
          <label className="sr-only" htmlFor="doc-status">
            Filter status
          </label>
          <select
            id="doc-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100"
          >
            {["all", "queued", "processing", "indexed", "failed", "deleted"].map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "semua status" : s}
              </option>
            ))}
          </select>
          <span className="text-xs text-slate-500">
            {visible.length}/{files.length}
          </span>
        </div>
      )}

      <ul className="mt-4 divide-y divide-slate-800">
        {files.length === 0 && (
          <li className="py-6 text-center text-sm text-slate-500">
            Belum ada dokumen. Unggah file agar bisa ditanyakan di chat.
          </li>
        )}
        {files.length > 0 && visible.length === 0 && (
          <li className="py-6 text-center text-sm text-slate-500">
            Tidak ada dokumen yang cocok dengan filter.
          </li>
        )}
        {visible.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center gap-3 py-3">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-slate-100">{f.filename}</p>
              <p className="text-xs text-slate-500">
                {formatSize(f.size_bytes)} · v{f.current_version}
                {f.error && <span className="text-red-400"> · {f.error}</span>}
              </p>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${
                STATUS_STYLE[f.status] ?? "bg-slate-700 text-slate-300"
              }`}
            >
              {f.status}
            </span>
            <div className="flex items-center gap-2">
              <a
                href={downloadUrl(workspaceId, f.id)}
                target="_blank"
                rel="noreferrer noopener"
                className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
              >
                Unduh
              </a>
              {canContribute && (
                <button
                  onClick={() =>
                    void run(() => reindexFile(workspaceId, f.id), `${f.filename} dijadwalkan ulang.`)
                  }
                  className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Reindex
                </button>
              )}
              {canDelete && (
                <button
                  onClick={() =>
                    void run(() => deleteFile(workspaceId, f.id), `${f.filename} dihapus.`)
                  }
                  className="rounded-md border border-red-500/40 px-2 py-1 text-xs text-red-300 hover:bg-red-500/10"
                >
                  Hapus
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
