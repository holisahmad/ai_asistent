#!/usr/bin/env bash
# Dokter environment (Fase 9): diagnosa kesiapan mesin lokal sebelum
# `make infra` / `make api` / `make worker` / `make web`.
#
# Memeriksa: Docker daemon, container infra, port infra, .env + konfigurasi efektif
# (CoreSettings), serta konektivitas Postgres/Redis/MinIO. Bila ada yang merah, langkah
# perbaikan dicetak di bagian akhir.
#
# Pemakaian:
#   ./scripts/doctor.sh [--fix] [--timeout SECONDS]
#   make doctor            # hanya diagnosa
#   make doctor ARGS=--fix # perbaiki otomatis + tunggu hijau + diagnosa ulang
set -uo pipefail

cd "$(dirname "$0")/.."

FIX_MODE=0
WAIT_TIMEOUT=180 # batas tunggu per tahap saat --fix (khususnya boot Docker Desktop)

usage() {
  cat <<'USAGE'
Pemakaian: ./scripts/doctor.sh [--fix] [--timeout SECONDS]

  --fix              Terapkan perbaikan otomatis yang aman, tunggu layanan hijau,
                     lalu diagnosa ulang.
  --timeout SECONDS  Batas tunggu per tahap saat --fix (default 180).
  -h, --help         Tampilkan bantuan ini.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --fix) FIX_MODE=1 ;;
    --timeout)
      shift
      WAIT_TIMEOUT="${1:-180}"
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Argumen tidak dikenal: $1"
      usage
      exit 2
      ;;
  esac
  shift
done

# --- Helper ---------------------------------------------------------------

# Jalankan perintah dengan batas waktu. Portabel: binary `timeout` tidak
# tersedia di macOS, jadi pakai background + polling.
run_with_timeout() {
  local secs="$1"
  shift
  local out_file
  out_file="$(mktemp)"
  "$@" >"${out_file}" 2>&1 &
  local pid=$! elapsed=0
  while kill -0 "${pid}" 2>/dev/null; do
    if [ "${elapsed}" -ge "${secs}" ]; then
      kill -TERM "${pid}" 2>/dev/null || true
      sleep 1
      kill -KILL "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
      cat "${out_file}"
      rm -f "${out_file}"
      return 124
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  wait "${pid}" 2>/dev/null
  local rc=$?
  cat "${out_file}"
  rm -f "${out_file}"
  return "${rc}"
}

pass() { printf '    %-40s : PASS (%s)\n' "$1" "$2"; }
fail() {
  printf '    %-40s : FAIL (%s)\n' "$1" "$2"
  FAILED=1
}
skip() { printf '    %-40s : SKIP (%s)\n' "$1" "$2"; }
add_fix() { FIXES+=("$1"); }

tcp_open() {
  (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null
}

# Ulangi predikat setiap 3s sampai batas waktu; kembalikan status predikat terakhir.
wait_for() {
  local secs="$1"
  shift
  local waited=0
  while [ "${waited}" -lt "${secs}" ]; do
    "$@" && return 0
    sleep 3
    waited=$((waited + 3))
    printf '    ... menunggu (%ds/%ds)\n' "${waited}" "${secs}"
  done
  "$@"
}

# --- Predikat kesiapan (dipakai diagnosis & mode --fix) -------------------

docker_ready() {
  run_with_timeout 8 docker info --format '{{.ServerVersion}}' >/dev/null 2>&1
}

infra_containers_ready() {
  local running
  running="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
  local entry name
  for entry in "${CONTAINERS[@]}"; do
    name="${entry%%:*}"
    printf '%s\n' "${running}" | grep -qx "${name}" || return 1
  done
}

infra_ports_ready() {
  local entry port
  for entry in "${INFRA_PORTS[@]}"; do
    port="${entry%%:*}"
    tcp_open localhost "${port}" || return 1
  done
}

# --- Konfigurasi yang diperiksa ------------------------------------------

CONTAINERS=(
  "aiassistant-postgres:make infra"
  "aiassistant-redis:make infra"
  "aiassistant-minio:make infra"
)

# port:label
INFRA_PORTS=(
  "5433:Postgres"
  "6380:Redis"
  "9000:MinIO API"
  "9001:MinIO Console"
)

# Memuat CoreSettings asli agar nilai efektif (default + override .env) ikut
# diperiksa — .env boleh hanya berisi override, bukan seluruh variabel.
read -r -d '' CONFIG_PY <<'PY' || true
from ai_asistent_core.config import get_settings

s = get_settings()
keys = [
    "database_url", "redis_url", "minio_endpoint", "minio_access_key",
    "minio_secret_key", "minio_bucket", "llm_provider", "embedding_provider",
]
empty = [k for k in keys if not getattr(s, k, None)]
print("EMPTY:" + ",".join(empty) if empty else "OK")
PY

# --- Pemeriksaan ----------------------------------------------------------

run_checks() {
  FIXES=()
  SEEN=()
  FAILED=0
  DOCKER_OK=0

  echo "==> Docker"
  DOCKER_VERSION="$(run_with_timeout 8 docker info --format '{{.ServerVersion}}' 2>&1)"
  if [ $? -eq 0 ]; then
    DOCKER_OK=1
    pass "docker daemon" "server ${DOCKER_VERSION}"
  else
    fail "docker daemon" "tidak dapat dihubungi"
    add_fix "Nyalakan Docker Desktop lalu ulangi: open -a Docker (tunggu ikon Docker siap, lalu 'make doctor')"
  fi

  echo "==> Container infra"
  if [ "${DOCKER_OK}" -eq 1 ]; then
    RUNNING="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
    for entry in "${CONTAINERS[@]}"; do
      name="${entry%%:*}"
      if printf '%s\n' "${RUNNING}" | grep -qx "${name}"; then
        pass "container ${name}" "berjalan"
      else
        fail "container ${name}" "tidak berjalan"
        add_fix "Jalankan infra: make infra (docker compose up -d --wait)"
      fi
    done
  else
    skip "container infra" "Docker daemon tidak aktif"
  fi

  echo "==> Port infra"
  for entry in "${INFRA_PORTS[@]}"; do
    port="${entry%%:*}"
    label="${entry#*:}"
    if tcp_open localhost "${port}"; then
      pass "port ${port} (${label})" "terbuka"
    else
      fail "port ${port} (${label})" "tertutup"
      if [ "${DOCKER_OK}" -eq 1 ]; then
        add_fix "Port ${port} tertutup padahal Docker aktif — cek konflik/baca log: lsof -iTCP:${port} -sTCP:LISTEN ; make infra"
      fi
    fi
  done

  # Port aplikasi bersifat opsional (hanya perlu saat dev server dijalankan).
  for entry in "8000:API (opsional)" "3000:Web (opsional)"; do
    port="${entry%%:*}"
    label="${entry#*:}"
    if tcp_open localhost "${port}"; then
      printf '    %-40s : %s\n' "port ${port} (${label})" "terbuka"
    else
      printf '    %-40s : %s\n' "port ${port} (${label})" "tertutup (bukan kegagalan)"
    fi
  done

  echo "==> Konfigurasi .env"
  if [ -f .env ]; then
    pass ".env" "ada"
  else
    fail ".env" "tidak ditemukan"
    add_fix "Buat file .env dari template: cp .env.example .env"
  fi

  echo "==> Konfigurasi efektif (CoreSettings)"
  if ! command -v uv >/dev/null 2>&1; then
    fail "uv" "tidak terpasang"
    add_fix "Pasang uv (https://docs.astral.sh/uv/) lalu jalankan: make install"
  else
    CONFIG_OUT="$(cd backend && run_with_timeout 30 uv run --no-sync python -c "${CONFIG_PY}" 2>&1)"
    rc=$?
    case "${CONFIG_OUT}" in
      *"EMPTY:"*)
        EMPTY_VARS="${CONFIG_OUT##*EMPTY:}"
        fail "CoreSettings" "nilai kosong: ${EMPTY_VARS}"
        add_fix "Isi variabel berikut di .env (lihat .env.example): ${EMPTY_VARS}"
        ;;
      *OK*)
        if [ "${rc}" -eq 0 ]; then
          pass "CoreSettings" "semua nilai penting terisi"
        else
          fail "CoreSettings" "pemuatan gagal"
          add_fix "Perbaiki .env lalu uji manual: cd backend && uv run python -c 'from ai_asistent_core.config import get_settings; get_settings()'"
        fi
        ;;
      *)
        fail "CoreSettings" "${CONFIG_OUT:-pemuatan gagal}"
        add_fix "Jalankan 'make install' lalu uji manual: cd backend && uv run python -c 'from ai_asistent_core.config import get_settings; get_settings()'"
        ;;
    esac
  fi

  echo "==> Konektivitas layanan"
  if [ "${DOCKER_OK}" -ne 1 ]; then
    skip "Postgres/Redis/MinIO" "Docker daemon tidak aktif"
  else
    # Postgres: pakai pg_isready di dalam container (host belum tentu punya psql).
    pg_out="$(run_with_timeout 8 docker exec aiassistant-postgres pg_isready -U ai_assistant -d ai_assistant 2>&1)"
    if [ $? -eq 0 ]; then
      pass "Postgres (pg_isready)" "${pg_out:-ok}"
    else
      fail "Postgres (pg_isready)" "${pg_out:-tidak merespons}"
      add_fix "Pastikan Postgres siap lalu migrasi: make infra ; make migrate"
    fi

    redis_out="$(run_with_timeout 8 docker exec aiassistant-redis redis-cli ping 2>&1)"
    if [ $? -eq 0 ] && printf '%s' "${redis_out}" | grep -q PONG; then
      pass "Redis (PING)" "PONG"
    else
      fail "Redis (PING)" "${redis_out:-tidak merespons}"
      add_fix "Pastikan Redis siap: make infra (docker compose up -d --wait)"
    fi

    if curl -fsS --max-time 5 http://localhost:9000/minio/health/live >/dev/null 2>&1; then
      pass "MinIO (health/live)" "HTTP 200"
    else
      fail "MinIO (health/live)" "tidak merespons"
      add_fix "Pastikan MinIO siap: make infra (docker compose up -d --wait)"
    fi
  fi
}

# --- Perbaikan otomatis (mode --fix) -------------------------------------

apply_fixes() {
  # 1. .env dari template (aman: .env gitignored).
  if [ ! -f .env ]; then
    if [ -f .env.example ]; then
      echo "==> Perbaikan: cp .env.example .env"
      cp .env.example .env
    else
      echo "==> Perbaikan dilewati: .env.example tidak ada"
    fi
  fi

  # 2. Docker Desktop (hanya bila daemon benar-benar belum siap).
  if ! docker_ready; then
    echo "==> Perbaikan: menyalakan Docker Desktop (open -a Docker)"
    open -a Docker 2>/dev/null || true
    if wait_for "${WAIT_TIMEOUT}" docker_ready; then
      echo "    Docker daemon siap."
    else
      echo "    Docker daemon belum siap setelah ${WAIT_TIMEOUT}s — lanjut mendiagnosa apa adanya."
    fi
  fi

  # 3. Infra (hanya bila daemon siap dan ada yang belum jalan).
  if docker_ready && { ! infra_containers_ready || ! infra_ports_ready; }; then
    echo "==> Perbaikan: docker compose up -d --wait"
    run_with_timeout $((WAIT_TIMEOUT + 180)) docker compose up -d --wait || true
    wait_for "${WAIT_TIMEOUT}" infra_ports_ready || true
  fi
}

# --- Ringkasan ------------------------------------------------------------

print_summary() {
  if [ "${FAILED}" -eq 0 ]; then
    echo "DOCTOR: PASS (environment siap untuk make infra/api/worker/web)"
    return 0
  fi

  echo
  echo "LANGKAH PERBAIKAN:"
  n=0
  for fix in "${FIXES[@]}"; do
    # Dedupe sederhana (bash 3.2 tidak punya associative array).
    dup=0
    for seen in ${SEEN[@]+"${SEEN[@]}"}; do
      [ "${seen}" = "${fix}" ] && dup=1 && break
    done
    if [ "${dup}" -eq 0 ]; then
      SEEN+=("${fix}")
      n=$((n + 1))
      printf '  %d. %s\n' "${n}" "${fix}"
    fi
  done

  echo "DOCTOR: FAIL — selesaikan langkah di atas, lalu jalankan ulang 'make doctor'"
  return 1
}

# --- Alur utama -----------------------------------------------------------

echo "AI Knowledge Assistant — doctor"
if [ "${FIX_MODE}" -eq 1 ]; then
  echo "(mode --fix: perbaikan otomatis lalu diagnosa ulang; timeout per tahap ${WAIT_TIMEOUT}s)"
fi

run_checks

if [ "${FAILED}" -ne 0 ] && [ "${FIX_MODE}" -eq 1 ]; then
  echo
  echo "==> Menerapkan perbaikan otomatis"
  apply_fixes
  echo
  echo "==> Diagnosa ulang"
  run_checks
fi

print_summary
