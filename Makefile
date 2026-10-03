.PHONY: help infra infra-down doctor install api worker worker-clean web lint typecheck test test-db migrate migration smoke clean backup restore restore-drill scan-secrets scan-deps eval bench reembed seed-demo pilot-check benchmark

help:
	@echo "AI Knowledge Assistant — perintah utama:"
	@echo "  make infra         Jalankan Postgres+Redis+MinIO (docker compose up -d --wait)"
	@echo "  make infra-down    Hentikan infra"
	@echo "  make doctor        Diagnosa environment (Docker, port infra, .env, DB/Redis/MinIO)"
	@echo "  make doctor ARGS=--fix   Perbaiki otomatis, tunggu hijau, lalu diagnosa ulang"
	@echo "  make install       Install semua workspace (uv sync di root) + npm install"
	@echo "  make api           Jalankan backend API di :8000 (reload)"
	@echo "  make worker        Jalankan RQ worker (queue: default)"
	@echo "  make worker-clean  Hapus registrasi worker lama dari Redis (bila 'worker-1 already exists')"
	@echo "  make web           Jalankan frontend Next.js di :3000"
	@echo "  make migrate       Jalankan migrasi Alembic (DB development)"
	@echo "  make migration m='pesan'   Buat file migrasi baru"
	@echo "  make test-db       (Sekali) buat & migrasi database test"
	@echo "  make lint          Ruff (core, backend, worker)"
	@echo "  make typecheck     mypy (core, backend, worker) + tsc (frontend)"
	@echo "  make test          pytest (core, backend, worker) + tsc (frontend)"
	@echo "  make smoke         Cek /health/live dan /health/ready"
	@echo "  make backup        Backup Postgres+MinIO ke ./backups/<timestamp>"
	@echo "  make restore DIR=backups/<ts> [DB=nama]  Restore backup ke database"
	@echo "  make restore-drill Backup lalu pulihkan ke DB scratch & bandingkan (PASS/FAIL)"
	@echo "  make scan-secrets  Pindai pola kredensial pada file tracked git"
	@echo "  make scan-deps     Audit dependensi Python (pip-audit) & Node (npm audit)"
	@echo "  make eval          Evaluasi kualitas RAG (ARGS='--write' untuk laporan)"
	@echo "  make bench         Benchmark p50/p95/p99 (ARGS='--iterations 50')"
	@echo "  make reembed       Hitung ulang embedding chunk (ARGS='--check' untuk cek)"
	@echo "  make seed-demo     Buat/verifikasi akun demo lokal (APP_DEMO_PASSWORD='...' make seed-demo)"
	@echo "  make pilot-check  Verifikasi kesiapan pilot end-to-end (10 cek otomatis)"
	@echo "  make benchmark    Benchmark p50/p95/p99 e2e (ARGS='http://host:port 100')"
	@echo "  make clean         Hapus artefak build (.next, __pycache__) — perbaiki 'Cannot find module ./*.js' (hentikan 'make web' dulu, lalu start ulang)"

infra:
	docker compose up -d --wait

infra-down:
	docker compose down

doctor:
	./scripts/doctor.sh $(ARGS)

install:
	uv sync
	cd frontend && npm install

api:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd worker && uv run python -m worker.main

worker-clean:
	@echo "Menghapus registrasi worker lama dari Redis..."
	redis-cli -p 6380 del rq:worker:worker-1 rq:workers rq:workers:default 2>/dev/null || true
	@echo "Jalankan 'make worker' sekarang."

web:
	cd frontend && npm run dev

migrate:
	cd backend && uv run alembic upgrade head

migration:
	@if [ -z "$(m)" ]; then echo "Pemakaian: make migration m='pesan migrasi'"; exit 1; fi
	cd backend && uv run alembic revision -m "$(m)"

test-db:
	docker exec aiassistant-postgres psql -U ai_assistant -d postgres -c "DROP DATABASE IF EXISTS ai_assistant_test;" -c "CREATE DATABASE ai_assistant_test;"
	cd backend && APP_DATABASE_URL="postgresql+psycopg://ai_assistant:ai_assistant@localhost:5433/ai_assistant_test" uv run alembic upgrade head

lint:
	cd core && uv run ruff check .
	cd backend && uv run ruff check .
	cd worker && uv run ruff check .

typecheck:
	cd core && uv run mypy src
	cd backend && uv run mypy app
	cd worker && uv run mypy src
	cd frontend && npx tsc --noEmit

test:
	cd core && uv run pytest -q
	cd backend && uv run pytest -q
	cd worker && uv run pytest -q
	cd frontend && npx tsc --noEmit

smoke:
	curl -fsS http://localhost:8000/health/live && echo
	curl -fsS http://localhost:8000/health/ready && echo

backup:
	./scripts/backup.sh

restore:
	@if [ -z "$(DIR)" ]; then echo "Pemakaian: make restore DIR=backups/<timestamp> [DB=nama]"; exit 1; fi
	./scripts/restore.sh "$(DIR)" $(DB)

restore-drill:
	./scripts/restore_drill.sh

scan-secrets:
	./scripts/scan_secrets.sh

scan-deps:
	./scripts/scan_deps.sh

eval:
	uv run --project backend python scripts/eval_rag.py $(ARGS)

bench:
	uv run --project backend python scripts/bench.py $(ARGS)

reembed:
	uv run --project backend python scripts/reembed.py $(ARGS)

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next 2>/dev/null || true

# Akun demo lokal untuk login ke web UI (idempotent, aman diulang).
# Password selalu lewat ENV — tidak ada kredensial hardcoded di repo.
seed-demo:
	APP_DEMO_PASSWORD="$(APP_DEMO_PASSWORD)" uv run --project backend python scripts/seed_demo_user.py

pilot-check:
	./scripts/pilot_check.sh $(ARGS)

benchmark:
	./scripts/benchmark.sh $(ARGS)
