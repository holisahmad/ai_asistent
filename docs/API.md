# API Reference — `ai_asistent` v1

Base URL: `http://localhost:8000/api/v1`

Semua endpoint membutuhkan header `Authorization: Bearer <token>` kecuali
`POST /auth/register` dan `POST /auth/login`.

Format error standar:
```json
{ "detail": "Pesan error" }
```

OpenAPI interaktif tersedia saat server berjalan di:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

---

## Autentikasi

### `POST /auth/register`

Daftar akun baru. Mengembalikan token session langsung (auto-login).

**Request body:**
```json
{
  "email": "user@example.com",
  "name": "Nama User",
  "password": "minimum8karakter"
}
```

**Response `201 Created`:**
```json
{
  "token": "tok_abc123...",
  "expires_at": "2026-10-10T10:00:00+00:00"
}
```

**Error:** `409` email sudah terdaftar.

---

### `POST /auth/login`

Login dengan email + password.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "minimum8karakter"
}
```

**Response `200 OK`:**
```json
{
  "token": "tok_abc123...",
  "expires_at": "2026-10-10T10:00:00+00:00"
}
```

**Error:** `401` email/password salah · `403` akun dinonaktifkan.

---

### `POST /auth/logout`

Revoke semua session aktif user yang sedang login.

**Response:** `204 No Content`

---

### `GET /auth/me`

Profil user yang sedang login.

**Response `200 OK`:**
```json
{
  "id": "usr_abc123",
  "email": "user@example.com",
  "name": "Nama User"
}
```

---

## Workspace

### `POST /workspaces`

Buat workspace baru. Pembuat otomatis menjadi `admin`.

**Request body:**
```json
{
  "name": "Nama Workspace",
  "slug": "nama-workspace"
}
```

> `slug`: huruf kecil, angka, dan dash; 3–100 karakter; contoh: `my-team`, `project-2026`

**Response `201 Created`:**
```json
{
  "id": "ws_abc123",
  "name": "Nama Workspace",
  "slug": "nama-workspace"
}
```

**Error:** `409` slug sudah dipakai.

---

### `GET /workspaces`

Daftar workspace tempat user menjadi anggota.

**Response `200 OK`:**
```json
[
  { "id": "ws_abc123", "name": "Nama Workspace", "slug": "nama-workspace" }
]
```

---

### `GET /workspaces/{workspace_id}`

Detail workspace + daftar anggota. Non-anggota menerima `404` (anti-enumeration).

**Role minimum:** `viewer`

**Response `200 OK`:**
```json
{
  "id": "ws_abc123",
  "name": "Nama Workspace",
  "slug": "nama-workspace",
  "members": [
    {
      "user_id": "usr_abc123",
      "email": "admin@example.com",
      "name": "Admin",
      "role": "admin"
    }
  ]
}
```

---

### `PATCH /workspaces/{workspace_id}`

Ubah nama workspace.

**Role minimum:** `admin`

**Request body:**
```json
{ "name": "Nama Baru" }
```

**Response `200 OK`:** objek workspace yang diperbarui.

---

### `POST /workspaces/{workspace_id}/members`

Tambah anggota baru.

**Role minimum:** `admin`

**Request body:**
```json
{
  "email": "member@example.com",
  "role": "contributor"
}
```

> `role`: `admin` | `editor` | `contributor` | `viewer`

**Response `201 Created`:**
```json
{
  "user_id": "usr_xyz789",
  "email": "member@example.com",
  "name": "Nama Member",
  "role": "contributor"
}
```

**Error:** `404` email tidak terdaftar · `409` sudah menjadi anggota.

---

### `DELETE /workspaces/{workspace_id}/members/{user_id}`

Hapus anggota dari workspace.

**Role minimum:** `admin`

**Response:** `204 No Content`

**Error:** `409` tidak bisa menghapus admin terakhir.

---

## File

Semua endpoint file ada di bawah `/workspaces/{workspace_id}/files`.

**Format tipe file yang didukung:**

| Ekstensi | MIME |
| --- | --- |
| `.pdf` | `application/pdf` |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.pptx` | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `.txt` | `text/plain` |
| `.md` | `text/markdown` |
| `.csv` | `text/csv` |
| `.html` | `text/html` |
| `.json` | `application/json` |

**Status lifecycle file:** `queued` → `processing` → `indexed` | `failed` | `deleted`

---

### `POST /workspaces/{workspace_id}/files`

Upload file baru. File dengan konten identik di workspace yang sama ditolak (`409`).

**Role minimum:** `contributor`

**Request:** `multipart/form-data` dengan field `file`.

Header opsional: `Idempotency-Key: <uuid>` — retry aman tanpa duplikat.

**Response `201 Created`:**
```json
{
  "id": "file_abc123",
  "workspace_id": "ws_abc123",
  "filename": "kebijakan-cuti.pdf",
  "size_bytes": 102400,
  "mime_type": "application/pdf",
  "checksum_sha256": "abcdef1234567890...",
  "status": "queued",
  "error": null,
  "current_version": 1,
  "created_at": "2026-10-03T10:00:00+00:00",
  "storage_key": "ws_abc123/file_abc123/v1/kebijakan-cuti.pdf"
}
```

**Error:** `400` file kosong · `409` konten duplikat · `413` file terlalu besar ·
`415` ekstensi tidak didukung · `422` konten mencurigakan (scan guard) · `502` storage tidak tersedia.

---

### `GET /workspaces/{workspace_id}/files`

Daftar file workspace, urutan terbaru lebih dulu.

**Role minimum:** `viewer`

**Query params:**
- `?status=queued|processing|indexed|failed|deleted` (opsional)

**Response `200 OK`:** array objek `FileOut`.

---

### `GET /workspaces/{workspace_id}/files/{file_id}`

Detail satu file.

**Role minimum:** `viewer`

**Response `200 OK`:** objek `FileOut`.

---

### `GET /workspaces/{workspace_id}/files/{file_id}/download`

Redirect `307` ke presigned URL MinIO. TTL diatur oleh `APP_PRESIGN_EXPIRY_SECONDS` (default 900 detik).

**Role minimum:** `viewer`

---

### `POST /workspaces/{workspace_id}/files/{file_id}/cancel`

Batalkan file yang masih `queued`.

**Role minimum:** `contributor`

**Response `200 OK`:**
```json
{ "id": "file_abc123", "status": "deleted" }
```

**Error:** `409` status bukan `queued`.

---

### `DELETE /workspaces/{workspace_id}/files/{file_id}`

Soft delete file (metadata tetap, storage object dibersihkan saat purge).

**Role minimum:** `editor`

**Response `200 OK`:**
```json
{ "id": "file_abc123", "status": "deleted" }
```

---

### `POST /workspaces/{workspace_id}/files/{file_id}/reindex`

Jadwalkan ulang indexing (mis. setelah update embedding model).

**Role minimum:** `contributor`

**Response `200 OK`:**
```json
{ "id": "file_abc123", "status": "queued" }
```

**Error:** `409` file sudah `queued`.

---

## Chat & RAG

### `POST /workspaces/{workspace_id}/chat/stream`

**Endpoint utama** — bertanya ke knowledge base. Mengembalikan SSE stream.

**Role minimum:** `viewer`

**Request body:**
```json
{
  "question": "Berapa hari cuti tahunan karyawan?",
  "chat_id": null,
  "allow_web": false
}
```

> - `chat_id`: `null` untuk membuat chat baru; isi untuk melanjutkan chat yang ada.
> - `allow_web`: aktifkan web fallback bila `APP_WEB_FALLBACK_MODE=internal_plus_web`.

**Response:** `text/event-stream` (Server-Sent Events)

```
event: meta
data: {"chat_id": "chat_abc123"}

event: delta
data: {"text": "Berdasarkan "}

event: delta
data: {"text": "dokumen internal [1]: "}

event: done
data: {
  "message_id": "msg_xyz789",
  "answer_kind": "grounded",
  "text": "Berdasarkan dokumen internal [1]: Karyawan berhak atas 12 hari cuti tahunan.",
  "citations": [
    {
      "idx": 1,
      "chunk_id": "chunk_abc",
      "file_id": "file_abc123",
      "filename": "kebijakan-cuti.pdf",
      "locator_type": "page",
      "locator_start": 3,
      "locator_end": 3,
      "snippet": "Karyawan tetap berhak atas 12 hari cuti tahunan...",
      "score": 0.873,
      "source_type": "internal",
      "url": null
    }
  ]
}
```

**Nilai `answer_kind`:**

| Nilai | Deskripsi |
| --- | --- |
| `grounded` | LLM menjawab dari konteks internal |
| `extractive` | Cuplikan verbatim tanpa LLM (`APP_ANSWER_MODE=extractive\|auto`) |
| `grounded_web` | LLM menjawab dari hasil web fallback |
| `no_answer` | Tidak ada bukti internal maupun web yang mencukupi |

**Error event (bila RAG gagal):**
```
event: error
data: {"message": "RAG failed: RuntimeError"}
```

---

### `POST /workspaces/{workspace_id}/chats/{chat_id}/messages/{message_id}/feedback`

Beri umpan balik pada jawaban assistant.

**Role minimum:** `viewer`

**Request body:**
```json
{ "feedback": "up" }
```

> `feedback`: `"up"` | `"down"` | `null` (menghapus feedback)

**Response `200 OK`:** objek `MessageOut`.

---

### `GET /workspaces/{workspace_id}/chats`

Daftar chat workspace, terbaru lebih dulu.

**Role minimum:** `viewer`

**Response `200 OK`:**
```json
[
  {
    "id": "chat_abc123",
    "title": "Berapa hari cuti tahunan karyawan?",
    "created_at": "2026-10-03T10:00:00+00:00",
    "message_count": 4
  }
]
```

---

### `GET /workspaces/{workspace_id}/chats/{chat_id}`

Detail chat beserta seluruh pesan dan sitasi.

**Role minimum:** `viewer`

**Response `200 OK`:**
```json
{
  "id": "chat_abc123",
  "title": "Berapa hari cuti tahunan karyawan?",
  "created_at": "2026-10-03T10:00:00+00:00",
  "message_count": 2,
  "messages": [
    {
      "id": "msg_user1",
      "role": "user",
      "content": "Berapa hari cuti tahunan karyawan?",
      "answer_kind": null,
      "feedback": null,
      "citations": [],
      "created_at": "2026-10-03T10:00:01+00:00"
    },
    {
      "id": "msg_asst1",
      "role": "assistant",
      "content": "Berdasarkan dokumen internal [1]: Karyawan berhak...",
      "answer_kind": "grounded",
      "feedback": "up",
      "citations": [...],
      "created_at": "2026-10-03T10:00:02+00:00"
    }
  ]
}
```

---

## Operasional

### `GET /health/live`

Liveness check — proses API hidup.

**Response `200 OK`:**
```json
{ "status": "alive" }
```

---

### `GET /health/ready`

Readiness check — DB dan Redis dapat dijangkau.

**Response `200 OK` (siap):**
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

**Response `503 Service Unavailable` (tidak siap):**
```json
{
  "status": "not_ready",
  "checks": {
    "database": "unavailable: OperationalError",
    "redis": "ok"
  }
}
```

---

### `GET /metrics`

Metrik format Prometheus text exposition.

Bila `APP_METRICS_TOKEN` diset, wajib header `Authorization: Bearer <token>`.

**Response `200 OK`:** `text/plain` — metrik Prometheus.

**Error:** `401` bila token tidak valid.

---

### `GET /version`

Versi aplikasi yang sedang berjalan.

**Response `200 OK`:**
```json
{
  "version": "0.1.0",
  "environment": "production"
}
```

---

## RBAC — Role Workspace

| Role | Upload file | Edit workspace | Tambah anggota | Chat (RAG) |
| --- | --- | --- | --- | --- |
| `admin` | ✅ | ✅ | ✅ | ✅ |
| `editor` | ✅ | ❌ | ❌ | ✅ |
| `contributor` | ✅ | ❌ | ❌ | ✅ |
| `viewer` | ❌ | ❌ | ❌ | ✅ |

Non-anggota workspace selalu menerima `404` (anti-enumeration).

---

## Catatan Klien

- **Token** — simpan di `localStorage` atau `httpOnly` cookie. Sertakan di header
  `Authorization: Bearer <token>` setiap request.
- **SSE** — gunakan `EventSource` atau `fetch` dengan `ReadableStream`. Peristiwa
  `done` menandakan akhir stream; `text` di dalamnya adalah teks final otoritatif.
- **Idempotency** — sertakan header `Idempotency-Key: <uuid-v4>` pada upload untuk
  retry aman. Respons tersimpan selama 24 jam.
- **Pagination** — endpoint daftar saat ini mengembalikan semua item; pagination
  berbasis cursor direncanakan di Fase 10.
