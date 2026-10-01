.PHONY: help infra infra-down install api worker web lint typecheck test smoke clean

help:
	@echo "AI Knowledge Assistant — perintah utama:"
	@echo "  make infra        Jalankan Postgres+Redis+MinIO (docker compose up -d --wait)"
	@echo "  make infra-down   Hentikan infra"
	@echo "  make install      Install deps backend+worker (uv) dan frontend (npm)"
	@echo "  make api          Jalankan backend API di :8000 (reload)"
	@echo "  make worker       Jalankan RQ worker (queue: default)"
	@echo "  make web          Jalankan frontend Next.js di :3000"
	@echo "  make lint         Ruff check (backend & worker)"
	@echo "  make typecheck    mypy (backend & worker) + tsc (frontend)"
	@echo "  make test         pytest (backend & worker) + tsc (frontend)"
	@echo "  make smoke        Cek /health/live dan /health/ready"

infra:
	docker compose up -d --wait

infra-down:
	docker compose down

install:
	cd backend && uv sync
	cd worker && uv sync
	cd frontend && npm install

api:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd worker && uv run python -m worker.main

web:
	cd frontend && npm run dev

lint:
	cd backend && uv run ruff check .
	cd worker && uv run ruff check .

typecheck:
	cd backend && uv run mypy app
	cd worker && uv run mypy worker
	cd frontend && npx tsc --noEmit

test:
	cd backend && uv run pytest -q
	cd worker && uv run pytest -q
	cd frontend && npx tsc --noEmit

smoke:
	curl -fsS http://localhost:8000/health/live && echo
	curl -fsS http://localhost:8000/health/ready && echo

clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/.next 2>/dev/null || true
