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

  async function handleUpload(file: File) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await uploadFile(workspaceId, file);
      setNotice(`${created.filename} diunggah — sedang diproses.`);
      await refresh();
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.status === 409
            ? "Isi file identik sudah ada di workspace ini."
            : err.detail
          : err instanceof Error
            ? err.message
            : "Upload gagal";
      setError(detail);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
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

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-white">Dokumen workspace</h2>
          <p className="text-sm text-slate-400">
            PDF, DOCX, PPTX, XLSX, TXT, MD, CSV, HTML, JSON · maks 100 MB
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
              disabled={busy}
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleUpload(f);
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
            const f = e.dataTransfer.files?.[0];
            if (f) void handleUpload(f);
          }}
          className={`mt-3 rounded-lg border border-dashed px-4 py-6 text-center text-sm transition ${
            dragging ? "border-sky-400 bg-sky-500/5 text-sky-200" : "border-slate-700 text-slate-400"
          }`}
        >
          Tarik & lepas file ke sini, atau klik “Unggah dokumen”.
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

      <ul className="mt-4 divide-y divide-slate-800">
        {files.length === 0 && (
          <li className="py-6 text-center text-sm text-slate-500">
            Belum ada dokumen. Unggah file agar bisa ditanyakan di chat.
          </li>
        )}
        {files.map((f) => (
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
