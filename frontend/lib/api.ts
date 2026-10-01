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

// --- Session (token opaque di localStorage) ---

const TOKEN_KEY = "ai_asistent_token";
const USER_KEY = "ai_asistent_user";

export type User = { id: string; email: string; name: string };

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: User): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* body non-JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Auth ---

type SessionOut = { token: string; expires_at: string };

export async function registerUser(
  email: string,
  name: string,
  password: string
): Promise<User> {
  const session = await apiFetch<SessionOut>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, name, password }),
  });
  const user = await apiFetch<User>("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  saveSession(session.token, user);
  return user;
}

export async function loginUser(email: string, password: string): Promise<User> {
  const session = await apiFetch<SessionOut>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  const user = await apiFetch<User>("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  saveSession(session.token, user);
  return user;
}

export async function logoutUser(): Promise<void> {
  try {
    await apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
  } finally {
    clearSession();
  }
}

export async function fetchMe(): Promise<User> {
  return apiFetch<User>("/api/v1/auth/me");
}

// --- Domain ---

export type Workspace = { id: string; name: string; slug: string };
export type WorkspaceDetail = Workspace & {
  members: { user_id: string; email: string; name: string; role: string }[];
};

export type FileItem = {
  id: string;
  workspace_id: string;
  filename: string;
  size_bytes: number;
  mime_type: string;
  status: string;
  error: string | null;
  current_version: number;
  created_at: string;
};

export type Citation = {
  idx: number;
  chunk_id: string | null;
  file_id: string | null;
  filename: string;
  locator_type: string;
  locator_start: number;
  locator_end: number;
  snippet: string;
  score: number;
  source_type: "internal" | "web";
  url: string | null;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  answer_kind: string | null;
  citations: Citation[];
  created_at: string;
};

export type Chat = { id: string; title: string; created_at: string; message_count: number };
export type ChatDetail = Chat & { messages: Message[] };

export const listWorkspaces = () => apiFetch<Workspace[]>("/api/v1/workspaces");

export const createWorkspace = (name: string, slug: string) =>
  apiFetch<Workspace>("/api/v1/workspaces", {
    method: "POST",
    body: JSON.stringify({ name, slug }),
  });

export const getWorkspace = (id: string) =>
  apiFetch<WorkspaceDetail>(`/api/v1/workspaces/${id}`);

export const listFiles = (wsId: string) =>
  apiFetch<FileItem[]>(`/api/v1/workspaces/${wsId}/files`);

export async function uploadFile(wsId: string, file: File): Promise<FileItem> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<FileItem>(`/api/v1/workspaces/${wsId}/files`, {
    method: "POST",
    body: form,
  });
}

export const reindexFile = (wsId: string, fileId: string) =>
  apiFetch<{ id: string; status: string }>(
    `/api/v1/workspaces/${wsId}/files/${fileId}/reindex`,
    { method: "POST" }
  );

export const deleteFile = (wsId: string, fileId: string) =>
  apiFetch<{ id: string; status: string }>(
    `/api/v1/workspaces/${wsId}/files/${fileId}`,
    { method: "DELETE" }
  );

export const downloadUrl = (wsId: string, fileId: string) =>
  `${API_BASE}/api/v1/workspaces/${wsId}/files/${fileId}/download`;

export const listChats = (wsId: string) =>
  apiFetch<Chat[]>(`/api/v1/workspaces/${wsId}/chats`);

export const getChat = (wsId: string, chatId: string) =>
  apiFetch<ChatDetail>(`/api/v1/workspaces/${wsId}/chats/${chatId}`);

// --- Chat streaming (SSE via fetch POST) ---

export type ChatStreamEvent =
  | { type: "meta"; chatId: string }
  | { type: "delta"; text: string }
  | {
      type: "done";
      messageId: string;
      answerKind: string;
      text: string;
      citations: Citation[];
    }
  | { type: "error"; message: string };

function parseSseBlock(block: string, emit: (ev: ChatStreamEvent) => void): void {
  let name = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) name = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!name || !data) return;
  try {
    const payload = JSON.parse(data) as Record<string, unknown>;
    if (name === "meta") {
      emit({ type: "meta", chatId: String(payload.chat_id ?? "") });
    } else if (name === "delta") {
      emit({ type: "delta", text: String(payload.text ?? "") });
    } else if (name === "done") {
      emit({
        type: "done",
        messageId: String(payload.message_id ?? ""),
        answerKind: String(payload.answer_kind ?? "grounded"),
        text: String(payload.text ?? ""),
        citations: (payload.citations as Citation[]) ?? [],
      });
    } else if (name === "error") {
      emit({ type: "error", message: String(payload.message ?? "unknown") });
    }
  } catch {
    /* blok tak valid diabaikan */
  }
}

export async function streamChat(
  wsId: string,
  body: { question: string; chatId?: string | null; allowWeb?: boolean },
  emit: (ev: ChatStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/workspaces/${wsId}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      question: body.question,
      chat_id: body.chatId ?? null,
      allow_web: body.allowWeb ?? false,
    }),
    signal,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error("Browser tidak mendukung streaming response");
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx = buffer.indexOf("\n\n");
    while (idx >= 0) {
      parseSseBlock(buffer.slice(0, idx), emit);
      buffer = buffer.slice(idx + 2);
      idx = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) parseSseBlock(buffer, emit);
}
