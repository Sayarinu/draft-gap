#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env.production}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${DEPLOY_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}"
  exit 1
fi

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
    docker compose "${COMPOSE_FILES[@]}" up -d "${ALL_SERVICES[@]}"
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
  docker compose "${COMPOSE_FILES[@]}" up -d "${ALL_SERVICES[@]}"

  log "Deployment finished."
}

main "$@"
