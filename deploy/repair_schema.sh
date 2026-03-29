#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml --env-file .env)
if [[ -f docker-compose.ci.yml ]]; then
  COMPOSE_FILES+=(-f docker-compose.ci.yml)
fi
source "$REPO_ROOT/deploy/runtime_validation.sh"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-draftgap}"
POSTGRES_DB="${POSTGRES_DB:-draftgap_db}"

echo "[repair] Backing up database first..."
"$REPO_ROOT/deploy/backup.sh"

echo "[repair] Inspecting current schema..."
docker compose "${COMPOSE_FILES[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"

BASELINE_QUERY="SELECT to_regclass('public.bankroll') IS NOT NULL
  AND to_regclass('public.bet') IS NOT NULL
  AND to_regclass('public.bankroll_snapshot') IS NOT NULL"
HAS_BASELINE="$(docker compose "${COMPOSE_FILES[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$BASELINE_QUERY" | tr -d '[:space:]')"
HAS_ALEMBIC="$(docker compose "${COMPOSE_FILES[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT to_regclass('public.alembic_version') IS NOT NULL" | tr -d '[:space:]')"

if [[ "$HAS_BASELINE" != "t" ]]; then
  echo "[repair] Expected baseline paper-trading tables are missing. Refusing to stamp automatically." >&2
  exit 1
fi

if [[ "$HAS_ALEMBIC" != "t" ]]; then
  echo "[repair] alembic_version is missing; stamping 20260308_01 before upgrade..."
  docker compose "${COMPOSE_FILES[@]}" run --rm api alembic stamp 20260308_01
fi

echo "[repair] Running alembic upgrade head..."
docker compose "${COMPOSE_FILES[@]}" run --rm api alembic upgrade head

echo "[repair] Restarting services..."
docker compose "${COMPOSE_FILES[@]}" restart api worker beat

echo "[repair] Rebuilding runtime snapshots..."
bootstrap_runtime_snapshots

echo "[repair] Smoke checking core endpoints..."
run_smoke_checks

echo "[repair] Verifying active snapshots..."
verify_snapshot_integrity

echo "[repair] Checking runtime diagnostics..."
run_runtime_diagnostics_check

echo "[repair] Complete."
