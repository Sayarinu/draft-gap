import json
import os
import sys

from tasks import (
    task_refresh_homepage_manifest,
    task_refresh_live_snapshot,
    task_refresh_rankings_snapshot,
    task_refresh_results_and_bankroll_snapshot,
    task_refresh_upcoming_snapshot,
    task_verify_model_health,
)


def _csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _status(result: dict[str, object]) -> str:
    return str(result.get("status", "")).lower()


def main() -> int:
    required_keys = _csv_env(
        "BOOTSTRAP_REQUIRED_KEYS",
        "upcoming,results_and_bankroll,rankings,homepage,model_health",
    )
    best_effort_keys = _csv_env("BOOTSTRAP_BEST_EFFORT_KEYS", "live")

    results = {
        "upcoming": task_refresh_upcoming_snapshot(),
        "live": task_refresh_live_snapshot(),
        "results_and_bankroll": task_refresh_results_and_bankroll_snapshot(),
        "rankings": task_refresh_rankings_snapshot(),
        "homepage": task_refresh_homepage_manifest(),
        "model_health": task_verify_model_health(),
    }
    print(json.dumps(results, indent=2, sort_keys=True))

    required_failures: list[str] = []
    for key in required_keys:
        status = _status(results.get(key, {}))
        if status != "success":
            required_failures.append(f"{key}={status or 'missing'}")

    best_effort_failures: list[str] = []
    for key in best_effort_keys:
        status = _status(results.get(key, {}))
        if status != "success":
            best_effort_failures.append(f"{key}={status or 'missing'}")

    if best_effort_failures:
        print(
            "bootstrap best-effort failures: " + ", ".join(best_effort_failures),
            file=sys.stderr,
        )

    if required_failures:
        print(
            "bootstrap required failures: " + ", ".join(required_failures),
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
