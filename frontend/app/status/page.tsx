"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchHealth, type HealthStatus } from "@/lib/api";

type ServiceState = {
  loading: boolean;
  result: { ok: boolean; data: HealthStatus | null; error?: string } | null;
};

function StatusDot({ ok, loading }: { ok: boolean | null; loading: boolean }) {
  if (loading) {
    return <span className="inline-block h-3 w-3 animate-pulse rounded-full bg-amber-400" />;
  }
  return (
    <span
      className={`inline-block h-3 w-3 rounded-full ${
        ok ? "bg-emerald-400" : "bg-red-500"
      }`}
    />
  );
}

export default function StatusPage() {
  const [live, setLive] = useState<ServiceState>({ loading: true, result: null });
  const [ready, setReady] = useState<ServiceState>({ loading: true, result: null });

  const refresh = useCallback(async () => {
    setLive({ loading: true, result: null });
    setReady({ loading: true, result: null });
    const [liveRes, readyRes] = await Promise.all([
      fetchHealth("/health/live"),
      fetchHealth("/health/ready"),
    ]);
    setLive({ loading: false, result: liveRes });
    setReady({ loading: false, result: readyRes });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Status Sistem</h1>
        <button
          onClick={() => void refresh()}
          className="rounded-lg border border-slate-700 px-4 py-1.5 text-sm text-slate-300 transition hover:bg-slate-800"
        >
          Refresh
        </button>
      </div>

      <ul className="mt-8 space-y-4">
        {[
          { name: "API (liveness)", state: live },
          { name: "API (readiness: DB & Redis)", state: ready },
        ].map(({ name, state }) => (
          <li
            key={name}
            className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/50 px-5 py-4"
          >
            <StatusDot
              ok={state.result ? state.result.ok : null}
              loading={state.loading}
            />
            <div>
              <p className="font-medium text-white">{name}</p>
              {state.result?.data?.checks && (
                <p className="mt-1 text-sm text-slate-400">
                  {Object.entries(state.result.data.checks)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
                </p>
              )}
              {state.result?.error && (
                <p className="mt-1 text-sm text-red-400">{state.result.error}</p>
              )}
            </div>
          </li>
        ))}
      </ul>

      <p className="mt-8 text-sm text-slate-500">
        Infrastruktur: PostgreSQL (:5433), Redis (:6380), MinIO (:9000) via
        Docker Compose. Jalankan <code className="text-slate-300">make infra</code>{" "}
        lalu <code className="text-slate-300">make api</code>.
      </p>
    </main>
  );
}
