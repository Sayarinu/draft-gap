#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
BACKUP_DIR="${BACKUP_DIR:-$REPO_ROOT/deploy/backup}"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-draftgap}"
POSTGRES_DB="${POSTGRES_DB:-draftgap_db}"

mkdir -p "$BACKUP_DIR"

echo "Backing up to $BACKUP_DIR ..."

echo "  postgres ..."
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  --no-owner --no-acl --clean --if-exists -F p \
  > "$BACKUP_DIR/postgres_dump.sql"
echo "  postgres done ($(wc -c < "$BACKUP_DIR/postgres_dump.sql") bytes)"

echo "  model_artifacts ..."
tar czf "$BACKUP_DIR/model_artifacts.tar.gz" -C "$REPO_ROOT/backend/models" .
echo "  model_artifacts done"

echo "  match_data ..."
docker compose run --rm -v match_data:/data -v "$BACKUP_DIR:/backup" \
  backup-helper tar czf /backup/match_data.tar.gz -C /data .
echo "  match_data done"

echo "Done. Copy deploy/backup/* to server and run deploy/restore.sh there."
