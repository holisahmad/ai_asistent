"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type User,
  type Workspace,
  ApiError,
  createWorkspace,
  fetchMe,
  getToken,
  getWorkspace,
  getUser,
  listWorkspaces,
  logoutUser,
} from "@/lib/api";
import ChatPanel from "./ChatPanel";
import FilesPanel from "./FilesPanel";

const ROLE_ORDER = ["viewer", "contributor", "editor", "admin"];

function roleAtLeast(role: string | null, minimum: string): boolean {
  if (!role) return false;
  return ROLE_ORDER.indexOf(role) >= ROLE_ORDER.indexOf(minimum);
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWsId, setActiveWsId] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [tab, setTab] = useState<"chat" | "dokumen">("chat");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [creating, setCreating] = useState(false);

  const loadWorkspaces = useCallback(async (selectFirst: boolean) => {
    const list = await listWorkspaces();
    setWorkspaces(list);
    if (selectFirst && list.length > 0) setActiveWsId(list[0].id);
    if (list.length === 0) setShowCreate(true);
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(getUser());
    (async () => {
      try {
        setUser(await fetchMe());
        await loadWorkspaces(true);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Gagal memuat data");
      } finally {
        setLoading(false);
      }
    })();
  }, [router, loadWorkspaces]);

  // Peran user di workspace aktif (RBAC tombol aksi).
  useEffect(() => {
    if (!activeWsId || !user) return;
    let cancelled = false;
    (async () => {
      try {
        const detail = await getWorkspace(activeWsId);
        if (cancelled) return;
        const me = detail.members.find((m) => m.email === user.email);
        setRole(me?.role ?? null);
      } catch {
        if (!cancelled) setRole(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeWsId, user]);

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const ws = await createWorkspace(newName.trim(), newSlug.trim());
      setNewName("");
      setNewSlug("");
      setShowCreate(false);
      await loadWorkspaces(false);
      setActiveWsId(ws.id);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 409
            ? "Slug sudah dipakai — coba slug lain."
            : err.detail
          : err instanceof Error
            ? err.message
            : "Gagal membuat workspace"
      );
    } finally {
      setCreating(false);
    }
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-16">
        <p className="text-slate-400">Memuat dashboard…</p>
      </main>
    );
  }

  const activeWs = workspaces.find((w) => w.id === activeWsId) ?? null;

  return (
    <main className="mx-auto max-w-6xl px-6 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <Link
            href="/"
            className="text-xs font-medium tracking-widest text-sky-400 uppercase"
          >
            AI Knowledge Assistant
          </Link>
          <h1 className="mt-1 text-2xl font-bold text-white">Workspace</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-slate-400">{user?.email}</span>
          {role && (
            <span className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-400">
              {role}
            </span>
          )}
          <button
            onClick={() => {
              void logoutUser().finally(() => router.replace("/login"));
            }}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800"
          >
            Keluar
          </button>
        </div>
      </header>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-400" htmlFor="ws-select">
          Workspace
        </label>
        <select
          id="ws-select"
          value={activeWsId ?? ""}
          onChange={(e) => setActiveWsId(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
        >
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800"
        >
          + Workspace baru
        </button>
      </div>

      {showCreate && (
        <form
          onSubmit={submitCreate}
          className="mt-4 flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
        >
          <label className="text-sm">
            <span className="text-slate-400">Nama</span>
            <input
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
                if (!newSlug) {
                  setNewSlug(
                    e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-|-$/g, "")
                  );
                }
              }}
              required
              className="mt-1 block rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
              placeholder="Tim Produk"
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-400">Slug</span>
            <input
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              required
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              className="mt-1 block rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
              placeholder="tim-produk"
            />
          </label>
          <button
            type="submit"
            disabled={creating}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-white hover:bg-sky-400 disabled:opacity-60"
          >
            {creating ? "Membuat…" : "Buat"}
          </button>
        </form>
      )}

      {error && (
        <p role="alert" className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {activeWs ? (
        <>
          <nav className="mt-6 flex gap-2 border-b border-slate-800" role="tablist">
            {(
              [
                ["chat", "Chat"],
                ["dokumen", "Dokumen"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm transition ${
                  tab === key
                    ? "border-sky-400 text-sky-300"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>

          <div className="mt-5">
            {tab === "chat" ? (
              <ChatPanel workspaceId={activeWs.id} />
            ) : (
              <FilesPanel
                workspaceId={activeWs.id}
                canContribute={roleAtLeast(role, "contributor")}
                canDelete={roleAtLeast(role, "editor")}
              />
            )}
          </div>
        </>
      ) : (
        <p className="mt-8 text-slate-400">
          Belum ada workspace. Buat workspace pertama untuk mulai mengunggah dokumen.
        </p>
      )}
    </main>
  );
}
