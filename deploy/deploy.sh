#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${DEPLOY_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}"
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml --env-file "${ENV_FILE}")
if [[ -f docker-compose.ci.yml ]]; then
  COMPOSE_FILES+=(-f docker-compose.ci.yml)
  USE_PREBUILT=1
else
  USE_PREBUILT=
fi
BUILD_SERVICES=(api worker beat frontend)
ALL_SERVICES=(db redis api worker beat frontend caddy)
MIN_FREE_GB="${MIN_FREE_GB:-6}"
PULL_FLAG="${PULL_FLAG:-}"

log() {
  printf '[deploy] %s\n' "$*"
}

source "${SCRIPT_DIR}/runtime_validation.sh"

prepare_migration_state() {
  local has_alembic has_bankroll has_bet has_bankroll_snapshot baseline_count

  has_alembic="$(db_psql_scalar "SELECT to_regclass('public.alembic_version') IS NOT NULL")"
  if [[ "${has_alembic}" == "t" ]]; then
    return 0
  fi

  has_bankroll="$(db_psql_scalar "SELECT to_regclass('public.bankroll') IS NOT NULL")"
  has_bet="$(db_psql_scalar "SELECT to_regclass('public.bet') IS NOT NULL")"
  has_bankroll_snapshot="$(db_psql_scalar "SELECT to_regclass('public.bankroll_snapshot') IS NOT NULL")"

  baseline_count=0
  [[ "${has_bankroll}" == "t" ]] && baseline_count=$((baseline_count + 1))
  [[ "${has_bet}" == "t" ]] && baseline_count=$((baseline_count + 1))
  [[ "${has_bankroll_snapshot}" == "t" ]] && baseline_count=$((baseline_count + 1))

  if (( baseline_count == 0 )); then
    log "No existing paper-trading baseline tables detected; applying full migration chain."
    return 0
  fi

  if (( baseline_count != 3 )); then
    log "Detected partially initialized legacy schema without alembic_version; refusing automatic stamp."
    return 1
  fi

  log "Legacy paper-trading tables detected without alembic_version; stamping 20260308_01."
  docker compose "${COMPOSE_FILES[@]}" run --rm api alembic stamp 20260308_01
}

run_migrations() {
  log "Running database migrations..."
  prepare_migration_state
  docker compose "${COMPOSE_FILES[@]}" run --rm api alembic upgrade head
}

wait_for_database() {
  log "Waiting for database readiness..."
  local attempts=30
  while (( attempts > 0 )); do
    if docker compose "${COMPOSE_FILES[@]}" exec -T db pg_isready -U "${POSTGRES_USER:-draftgap}" -d "${POSTGRES_DB:-draftgap_db}" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 2
  done
  log "Database did not become ready in time."
  return 1
}

docker_root_dir() {
  docker info --format '{{ .DockerRootDir }}'
}

free_gb_for_path() {
  local target_path="$1"
  df -BG "${target_path}" | awk 'NR==2 {gsub(/G/, "", $4); print $4}'
}

prune_docker_caches() {
  log "Pruning Docker build caches and unused artifacts..."
  docker builder prune -af || true
  docker buildx prune -af || true
  docker image prune -af || true
  docker container prune -f || true
}

build_images() {
  local build_log
  local -a build_args
  build_log="$(mktemp)"
  build_args=(--progress=plain "${BUILD_SERVICES[@]}")
  if [[ -n "${PULL_FLAG}" ]]; then
    build_args=("${PULL_FLAG}" "${build_args[@]}")
  fi

  docker compose "${COMPOSE_FILES[@]}" build "${build_args[@]}" 2>&1 | tee "${build_log}"
  local exit_code="${PIPESTATUS[0]}"

  if [[ "${exit_code}" -ne 0 ]]; then
    if grep -q "no space left on device" "${build_log}"; then
      log "Build failed due to low disk space."
      rm -f "${build_log}"
      return 42
    fi
    rm -f "${build_log}"
    return "${exit_code}"
  fi

  rm -f "${build_log}"
  return 0
}

main() {
  if [[ -n "${USE_PREBUILT}" ]]; then
    log "Using prebuilt images (docker-compose.ci.yml); pulling and starting..."
    local docker_root free_gb
    docker_root="$(docker_root_dir)"
    free_gb="$(free_gb_for_path "${docker_root}")"
    log "Docker root: ${docker_root} (free: ${free_gb}G)"
    if (( free_gb < MIN_FREE_GB )); then
      log "Free disk below ${MIN_FREE_GB}G; pruning unused images and build cache before pull."
      prune_docker_caches
    else
      log "Pruning unused images from previous deploys..."
      docker image prune -af || true
    fi
    docker compose "${COMPOSE_FILES[@]}" pull "${BUILD_SERVICES[@]}"
    docker compose "${COMPOSE_FILES[@]}" up -d db redis
    wait_for_database
    run_migrations
    docker compose "${COMPOSE_FILES[@]}" up -d api worker beat frontend caddy
    bootstrap_runtime_snapshots
    run_smoke_checks
    verify_snapshot_integrity
    run_runtime_diagnostics_check
    docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate --no-deps caddy
    log "Deployment finished."
    return 0
  fi

  local docker_root free_gb
  docker_root="$(docker_root_dir)"
  free_gb="$(free_gb_for_path "${docker_root}")"
  log "Docker root: ${docker_root} (free: ${free_gb}G)"

  if (( free_gb < MIN_FREE_GB )); then
    log "Free disk is below ${MIN_FREE_GB}G; running pre-build cleanup."
    prune_docker_caches
  fi

  if ! build_images; then
    local build_status="$?"
    if [[ "${build_status}" -eq 42 ]]; then
      log "Retrying once after cleanup..."
      prune_docker_caches
      build_images
    else
      exit "${build_status}"
    fi
  fi

  log "Starting/updating services..."
  docker compose "${COMPOSE_FILES[@]}" up -d db redis
  wait_for_database
  run_migrations
  docker compose "${COMPOSE_FILES[@]}" up -d api worker beat frontend caddy
  bootstrap_runtime_snapshots
  run_smoke_checks
  verify_snapshot_integrity
  run_runtime_diagnostics_check
  docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate --no-deps caddy

  log "Deployment finished."
}

main "$@"
