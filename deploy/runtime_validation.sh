#!/usr/bin/env bash

runtime_log() {
  if declare -F log >/dev/null 2>&1; then
    log "$*"
  else
    printf '[runtime] %s\n' "$*"
  fi
}

admin_api_key() {
  printf '%s' "${ADMIN_API_KEY:-${FRONTEND_API_SECRET:-}}"
}

db_psql_scalar() {
  local sql="$1"
  docker compose "${COMPOSE_FILES[@]}" exec -T db \
    psql -U "${POSTGRES_USER:-draftgap}" -d "${POSTGRES_DB:-draftgap_db}" -tAc "${sql}" | tr -d '[:space:]'
}

safe_db_psql_scalar() {
  local label="$1"
  local sql="$2"
  local value
  if ! value="$(db_psql_scalar "${sql}")"; then
    runtime_log "Failed reading database scalar for ${label}"
    runtime_log "SQL: ${sql}"
    return 1
  fi
  printf '%s' "${value}"
}

bootstrap_runtime_snapshots() {
  runtime_log "Bootstrapping runtime snapshots..."
  docker compose "${COMPOSE_FILES[@]}" run --rm \
    -e BOOTSTRAP_REQUIRED_KEYS="${BOOTSTRAP_REQUIRED_KEYS:-upcoming,results_and_bankroll,rankings,homepage,model_health}" \
    -e BOOTSTRAP_BEST_EFFORT_KEYS="${BOOTSTRAP_BEST_EFFORT_KEYS:-live}" \
    api python scripts/runtime_bootstrap.py
}

run_smoke_checks() {
  runtime_log "Waiting for API readiness..."
  local readiness_endpoint="http://localhost:8000/health"
  local readiness_attempts=30
  while (( readiness_attempts > 0 )); do
    if docker compose "${COMPOSE_FILES[@]}" exec -T api curl -fsS "${readiness_endpoint}" >/dev/null 2>&1; then
      break
    fi
    readiness_attempts=$((readiness_attempts - 1))
    sleep 2
  done

  if (( readiness_attempts == 0 )); then
    runtime_log "API did not become ready in time."
    return 1
  fi

  runtime_log "Running API smoke checks..."
  local endpoints=(
    "http://localhost:8000/api/v1/homepage/bootstrap"
    "http://localhost:8000/api/v1/betting/bankroll"
    "http://localhost:8000/api/v1/pandascore/lol/upcoming-with-odds"
  )
  for endpoint in "${endpoints[@]}"; do
    docker compose "${COMPOSE_FILES[@]}" exec -T api curl -fsS "${endpoint}" >/dev/null
  done
}

verify_snapshot_integrity() {
  runtime_log "Verifying active snapshot families..."
  local require_live_snapshot="${REQUIRE_LIVE_SNAPSHOT:-0}"
  local upcoming_count live_count results_count bankroll_count rankings_count homepage_count total_bets settled_bets
  upcoming_count="$(safe_db_psql_scalar "active upcoming snapshot count" "SELECT COUNT(*) FROM upcoming_with_odds_snapshot WHERE is_active = true")"
  live_count="$(safe_db_psql_scalar "active live snapshot count" "SELECT COUNT(*) FROM live_with_odds_snapshot WHERE is_active = true")"
  results_count="$(safe_db_psql_scalar "active results snapshot count" "SELECT COUNT(*) FROM betting_results_snapshot WHERE is_active = true")"
  bankroll_count="$(safe_db_psql_scalar "active bankroll snapshot count" "SELECT COUNT(*) FROM bankroll_summary_snapshot WHERE is_active = true")"
  rankings_count="$(safe_db_psql_scalar "active rankings snapshot count" "SELECT COUNT(*) FROM power_rankings_snapshot WHERE is_active = true")"
  homepage_count="$(safe_db_psql_scalar "active homepage snapshot count" "SELECT COUNT(*) FROM homepage_snapshot_manifest WHERE is_active = true")"
  total_bets="$(safe_db_psql_scalar "total bet count" "SELECT COUNT(*) FROM bet")"
  settled_bets="$(safe_db_psql_scalar "settled bet count" "SELECT COUNT(*) FROM bet WHERE status IN ('WON','LOST')")"

  [[ "${upcoming_count}" -gt 0 ]] || { runtime_log "Missing active upcoming snapshot"; return 1; }
  if [[ "${require_live_snapshot}" == "1" ]]; then
    [[ "${live_count}" -gt 0 ]] || { runtime_log "Missing active live snapshot"; return 1; }
  elif [[ "${live_count}" -le 0 ]]; then
    runtime_log "No active live snapshot present; continuing because live data is best-effort during deploy."
  fi
  [[ "${results_count}" -gt 0 ]] || { runtime_log "Missing active results snapshot"; return 1; }
  [[ "${bankroll_count}" -gt 0 ]] || { runtime_log "Missing active bankroll snapshot"; return 1; }
  [[ "${rankings_count}" -gt 0 ]] || { runtime_log "Missing active rankings snapshot"; return 1; }
  [[ "${homepage_count}" -gt 0 ]] || { runtime_log "Missing active homepage snapshot"; return 1; }

  if [[ "${total_bets}" -gt 0 && "${settled_bets}" -gt 0 ]]; then
    local results_items
    results_items="$(safe_db_psql_scalar "results snapshot item count" "SELECT COALESCE(jsonb_array_length(payload_json->'items'), 0) FROM betting_results_snapshot WHERE is_active = true ORDER BY generated_at DESC, id DESC LIMIT 1")"
    [[ "${results_items}" -gt 0 ]] || { runtime_log "Settled bets exist but active results snapshot is empty"; return 1; }
  fi
}

run_runtime_diagnostics_check() {
  runtime_log "Checking runtime diagnostics..."
  local api_key payload
  api_key="$(admin_api_key)"
  if [[ -z "${api_key}" ]]; then
    runtime_log "ADMIN_API_KEY or FRONTEND_API_SECRET is required for runtime diagnostics."
    return 1
  fi

  payload="$(docker compose "${COMPOSE_FILES[@]}" exec -T api python - <<PY
import json
import sys
import urllib.request

req = urllib.request.Request(
    "http://localhost:8000/api/v1/admin/runtime-status",
    headers={"X-Admin-Key": "${api_key}", "Accept": "application/json"},
)
with urllib.request.urlopen(req, timeout=30) as response:
    data = json.load(response)
print(json.dumps(data))
issues = data.get("detected_issues") or []
loaded_model_id = ((data.get("model_runtime") or {}).get("loaded_model_id"))
if loaded_model_id is None:
    print("No loadable active model in runtime diagnostics.", file=sys.stderr)
    sys.exit(1)
if issues:
    print("Runtime diagnostics reported issues: " + "; ".join(str(issue) for issue in issues), file=sys.stderr)
    sys.exit(1)
PY
)" || return 1

  [[ -n "${payload}" ]] || { runtime_log "Runtime diagnostics returned no payload"; return 1; }
}
