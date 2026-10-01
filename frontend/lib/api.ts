const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type HealthStatus = {
  status: string;
  checks?: Record<string, string>;
};

export async function fetchHealth(
  path: "/health/live" | "/health/ready"
): Promise<{ ok: boolean; data: HealthStatus | null; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    return { ok: res.ok, data: (await res.json()) as HealthStatus };
  } catch (err) {
    return {
      ok: false,
      data: null,
      error: err instanceof Error ? err.message : "unknown error",
    };
  }
}
