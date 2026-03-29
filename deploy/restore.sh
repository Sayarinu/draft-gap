#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/deploy/backup}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml --env-file .env)
if [[ -f docker-compose.ci.yml ]]; then
  COMPOSE_FILES+=(-f docker-compose.ci.yml)
fi

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-draftgap}"
POSTGRES_DB="${POSTGRES_DB:-draftgap_db}"

if [[ ! -f "$BACKUP_DIR/postgres_dump.sql" ]]; then
  echo "Missing $BACKUP_DIR/postgres_dump.sql. Run backup.sh locally and copy deploy/backup/ here." >&2
  exit 1
fi

echo "Restoring from $BACKUP_DIR ..."

echo "  postgres ..."
docker compose "${COMPOSE_FILES[@]}" exec -T db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_DIR/postgres_dump.sql"
echo "  postgres done"

echo "  migrations ..."
docker compose "${COMPOSE_FILES[@]}" run --rm api \
  alembic upgrade head
echo "  migrations done"

if [[ -f "$BACKUP_DIR/model_artifacts.tar.gz" ]]; then
  echo "  model_artifacts ..."
  mkdir -p "$REPO_ROOT/backend/models"
  tar xzf "$BACKUP_DIR/model_artifacts.tar.gz" -C "$REPO_ROOT/backend/models"
  echo "  model_artifacts done"
fi

if [[ -f "$BACKUP_DIR/match_data.tar.gz" ]]; then
  echo "  match_data ..."
  docker compose "${COMPOSE_FILES[@]}" run --rm \
    -v match_data:/data -v "$BACKUP_DIR:/backup" backup-helper \
    sh -c "cd /data && tar xzf /backup/match_data.tar.gz"
  echo "  match_data done"
fi

echo "Restore complete. Restart api and worker to pick up changes:"
echo "  docker compose ${COMPOSE_FILES[*]} restart api worker"
