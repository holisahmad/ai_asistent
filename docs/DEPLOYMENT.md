# Deployment Guide — AI Knowledge Assistant

Stack: **Railway** (backend API) + **Supabase** (PostgreSQL) + **Vercel** (frontend Next.js)

---

## 1. Supabase — Setup Database

### Connection String
Dari Supabase dashboard → **Settings → Database → Connection string → URI**:
```
postgresql://postgres:[PASSWORD]@db.[PROJECT_ID].supabase.co:5432/postgres
```

Salin URL ini. Tidak perlu ubah prefix — `config.py` otomatis konvert ke `postgresql+psycopg://`.

**Project ID:** `nykffalzlxbmuatxgbhb`  
**Host:** `db.nykffalzlxbmuatxgbhb.supabase.co`  
**Port:** `5432`  
**DB:** `postgres`  
**User:** `postgres`

> Untuk pooler (Supavisor) gunakan port **6543** dengan `?pgbouncer=true` di URL.

---

## 2. Railway — Environment Variables

Di Railway dashboard → project → **Variables**, set semua ini:

### Wajib
| Variable | Nilai |
|---|---|
| `APP_DATABASE_URL` | `postgresql://postgres:Maduraonline254@db.nykffalzlxbmuatxgbhb.supabase.co:5432/postgres?sslmode=require` |
| `APP_REDIS_URL` | URL Redis Railway yang auto-generate (lihat Redis service) |
| `APP_ENVIRONMENT` | `production` |
| `APP_LOG_LEVEL` | `INFO` |

### CORS — wajib agar frontend bisa akses API
| Variable | Nilai |
|---|---|
| `APP_CORS_ORIGINS_CSV` | `https://ai-asistent-nu.vercel.app` |

### Object Storage (MinIO/S3) — wajib untuk upload file
| Variable | Nilai |
|---|---|
| `APP_MINIO_ENDPOINT` | endpoint S3/MinIO kamu |
| `APP_MINIO_ACCESS_KEY` | access key |
| `APP_MINIO_SECRET_KEY` | secret key |
| `APP_MINIO_BUCKET` | `ai-assistant` |
| `APP_MINIO_SECURE` | `true` |

### LLM (opsional, bisa pakai `local` untuk testing)
| Variable | Nilai |
|---|---|
| `APP_LLM_PROVIDER` | `openai` atau `local` |
| `APP_OPENAI_API_KEY` | sk-... |
| `APP_OPENAI_CHAT_MODEL` | `gpt-4o-mini` |

### Embedding
| Variable | Nilai |
|---|---|
| `APP_EMBEDDING_PROVIDER` | `local` (tanpa GPU/key) atau `openai` |

---

## 3. Railway — Mendapatkan Public URL

Setelah deploy pertama berhasil:
1. Railway dashboard → service → **Settings → Networking**
2. Klik **Generate Domain** → copy URL (contoh: `https://ai-asistent-production.up.railway.app`)
3. URL ini dipakai untuk `NEXT_BACKEND_URL` di Vercel

---

## 4. Vercel — Environment Variables

Di Vercel dashboard → project **ai_asistent** → **Settings → Environment Variables**:

| Variable | Environment | Nilai |
|---|---|---|
| `NEXT_BACKEND_URL` | Production | `https://ai-asistent-production.up.railway.app` |
| `NEXT_BACKEND_URL` | Preview | `https://ai-asistent-production.up.railway.app` |
| `NEXT_PUBLIC_API_BASE` | All | *(kosongkan / hapus)* |

> `NEXT_BACKEND_URL` dipakai oleh `next.config.ts` untuk proxy rewrites server-side.  
> `NEXT_PUBLIC_API_BASE` **tidak perlu diset** di production — biarkan kosong.

### Vercel Build Settings
Di **Settings → General**:
- **Root Directory:** *(kosong — vercel.json sudah set buildCommand)*
- **Framework:** Next.js

---

## 5. Vercel — Update Railway URL di vercel.json

Edit `/vercel.json`, ganti URL Railway di bagian `rewrites`:
```json
"destination": "https://RAILWAY_URL_KAMU/api/:path*"
```

Lalu commit & push — Vercel auto-redeploy.

---

## 6. Migrasi Database ke Supabase

Jalankan dari local (sekali, saat pertama deploy):

```bash
export APP_DATABASE_URL="postgresql://postgres:Maduraonline254@db.nykffalzlxbmuatxgbhb.supabase.co:5432/postgres?sslmode=require"
./scripts/migrate_prod.sh
```

Atau via Railway: migrasi otomatis dijalankan di CMD Dockerfile setiap kali container start.

---

## 7. Verifikasi Akhir

```bash
# Cek backend hidup
curl https://RAILWAY_URL/health/live

# Cek DB & Redis
curl https://RAILWAY_URL/health/ready

# Cek frontend → proxy → backend
curl https://ai-asistent-nu.vercel.app/health/live
```

Response yang benar:
```json
{"status":"alive"}
{"status":"ready","checks":{"database":"ok","redis":"ok"}}
```

---

## 8. Urutan Deploy

1. ✅ Setup Supabase (sudah ada, password: `Maduraonline254`)
2. ✅ Deploy Railway (Dockerfile) — set env vars di atas
3. ✅ Jalankan migrasi (otomatis via CMD, atau manual via `migrate_prod.sh`)
4. ✅ Copy Railway URL → set `NEXT_BACKEND_URL` di Vercel
5. ✅ Update `vercel.json` rewrites dengan Railway URL yang benar
6. ✅ Redeploy Vercel
7. ✅ Buka `https://ai-asistent-nu.vercel.app/status` — semua hijau

---

## Troubleshooting

| Error | Penyebab | Fix |
|---|---|---|
| `uvicorn: command not found` | Railway pakai Nixpacks, bukan Dockerfile | Pastikan `railway.json` punya `"builder": "DOCKERFILE"` |
| `Unexpected token '<'...` | Frontend memanggil URL yang balik HTML (404) | Set `NEXT_BACKEND_URL` di Vercel ke URL Railway yang benar |
| `database: unavailable` | `APP_DATABASE_URL` salah / belum diset | Cek Railway env vars, pastikan Supabase URL dengan `?sslmode=require` |
| `redis: unavailable` | `APP_REDIS_URL` belum diset | Tambahkan Redis service di Railway, copy URL-nya |
| CORS error di browser | `APP_CORS_ORIGINS_CSV` belum include Vercel domain | Set ke `https://ai-asistent-nu.vercel.app` di Railway |
| Migration gagal di container | `PYTHONPATH` tidak include `core/src` | Sudah difix di Dockerfile via `ENV PYTHONPATH="/app/core/src"` |
