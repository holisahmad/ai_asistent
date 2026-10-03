"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  getToken,
  loginUser,
  registerUser,
} from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (getToken()) router.replace("/app");
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await registerUser(email, name || email.split("@")[0], password);
      } else {
        await loginUser(email, password);
      }
      router.push("/app");
    } catch (err) {
      const detail =
        err instanceof ApiError
          ? err.status === 401
            ? "Email atau password salah."
            : err.detail
          : err instanceof Error
            ? err.message
            : "Gagal masuk";
      setError(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
      <p className="text-sm font-medium tracking-widest text-sky-400 uppercase">
        AI Knowledge Assistant
      </p>
      <h1 className="mt-3 text-3xl font-bold text-white">
        {mode === "login" ? "Masuk ke workspace" : "Buat akun baru"}
      </h1>
      <p className="mt-2 text-sm text-slate-400">
        Jawaban berbasis dokumen internal, lengkap dengan sitasi.
      </p>

      <form onSubmit={submit} className="mt-8 space-y-4">
        <label className="block">
          <span className="text-sm text-slate-300">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none focus:border-sky-500"
            placeholder="nama@perusahaan.com"
            autoComplete="email"
            suppressHydrationWarning
          />
        </label>

        {mode === "register" && (
          <label className="block">
            <span className="text-sm text-slate-300">Nama</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none focus:border-sky-500"
              placeholder="Nama lengkap"
              autoComplete="name"
              suppressHydrationWarning
            />
          </label>
        )}

        <label className="block">
          <span className="text-sm text-slate-300">Password</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 outline-none focus:border-sky-500"
            placeholder="minimal 8 karakter"
            autoComplete="current-password"
            suppressHydrationWarning
          />
        </label>

        {error && (
          <p role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-sky-500 px-4 py-2.5 font-medium text-white transition hover:bg-sky-400 disabled:opacity-60"
          suppressHydrationWarning
        >
          {busy ? "Memproses…" : mode === "login" ? "Masuk" : "Daftar & masuk"}
        </button>
      </form>

      <button
        onClick={() => {
          setMode(mode === "login" ? "register" : "login");
          setError(null);
        }}
        className="mt-6 text-sm text-slate-400 underline-offset-4 hover:text-sky-400 hover:underline"
        suppressHydrationWarning
      >
        {mode === "login"
          ? "Belum punya akun? Daftar"
          : "Sudah punya akun? Masuk"}
      </button>
    </main>
  );
}
