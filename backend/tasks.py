import io
import logging
import os
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

from celery.result import AsyncResult

from typing_utils import TaskResult
from database import engine, SessionLocal, init_db
from services.cloudflare_cache import purge_cloudflare_cache
from services.homepage_snapshots import (
    build_bankroll_summary_payload,
    build_betting_results_payload,
    build_homepage_manifest_payload,
    build_live_snapshot_payload,
    build_power_rankings_payload,
    build_snapshot_version,
    build_upcoming_snapshot_payload,
    create_snapshot,
    record_snapshot_failure,
    utc_now,
)
from models_ml import (
    BankrollSummarySnapshot,
    BettingResultsSnapshot,
    HomepageSnapshotManifest,
    LiveWithOddsSnapshot,
    PowerRankingsSnapshot,
    UpcomingWithOddsSnapshot,
)
from services.odds_refresh_status import (
    clear_current_task_id,
    get_current_task_id,
    set_current_task_id,
    set_last_completed_at_now,
)
from worker import celery_app

logger = logging.getLogger(__name__)


def _task_window() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(name="refresh_pandascore_upcoming")
def refresh_pandascore_upcoming(tiers: str | None = None) -> TaskResult:
    from services.pandascore import download_upcoming_lol_fixtures

    tier_list = [t.strip() for t in tiers.split(",")] if tiers else None
    try:
        summary = download_upcoming_lol_fixtures(tiers=tier_list)
        return {
            "status": "error" if summary.get("errors") else "success",
            "saved": summary["saved"],
            "errors": summary.get("errors", []),
        }
    except Exception as e:
        logger.error(
            "task refresh_pandascore_upcoming failed: tiers=%s error_type=%s error=%s",
            tiers,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        return {"status": "error", "message": str(e), "saved": [], "errors": [str(e)]}


@celery_app.task(name="refresh_thunderpick_odds")
def refresh_thunderpick_odds() -> TaskResult:
    from services.bookie import scrape_lol_odds

    try:
        results = scrape_lol_odds()
        return {
            "status": "success",
            "matches_with_odds": len(results),
        }
    except Exception as e:
        logger.error(
            "task refresh_thunderpick_odds failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        return {"status": "error", "message": str(e), "matches_with_odds": 0}


@celery_app.task(name="refresh_bookie_odds")
def refresh_bookie_odds() -> TaskResult:
    return refresh_thunderpick_odds()


@celery_app.task(name="task_auto_place_bets")
def task_auto_place_bets() -> TaskResult:
    try:
        from betting.bet_manager import auto_place_bets

        init_db()
        session = SessionLocal()
        try:
            summary = auto_place_bets(session)
            return {
                "status": "success",
                "message": "Auto-placement completed",
                "results": [summary],
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_auto_place_bets failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_repair_orphaned_bets")
def task_repair_orphaned_bets() -> TaskResult:
    try:
        from betting.bet_manager import repair_orphaned_bets

        init_db()
        session = SessionLocal()
        try:
            summary = repair_orphaned_bets(session)
            results_and_bankroll_snapshot = task_refresh_results_and_bankroll_snapshot()
            homepage_manifest = task_refresh_homepage_manifest()
            return {
                "status": "success",
                "message": "Orphaned bet repair completed",
                "results": [summary],
                "results_and_bankroll_snapshot": results_and_bankroll_snapshot,
                "homepage_manifest": homepage_manifest,
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_repair_orphaned_bets failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_refresh_upcoming_snapshot")
def task_refresh_upcoming_snapshot() -> TaskResult:
    started_at = _task_window()
    version = build_snapshot_version("upcoming")
    init_db()
    session = SessionLocal()
    try:
        payload = build_upcoming_snapshot_payload()
        snapshot = create_snapshot(
            session,
            UpcomingWithOddsSnapshot,
            payload=payload,
            version=version,
            status="success",
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            activate=True,
        )
        return {
            "status": "success",
            "snapshot_version": snapshot.version,
            "items": len(payload.get("items", [])),
        }
    except Exception as e:
        logger.error("task_refresh_upcoming_snapshot failed: %s", e, exc_info=True)
        session.rollback()
        record_snapshot_failure(
            session,
            UpcomingWithOddsSnapshot,
            version=version,
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            message=str(e),
        )
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@celery_app.task(name="task_refresh_live_snapshot")
def task_refresh_live_snapshot() -> TaskResult:
    started_at = _task_window()
    version = build_snapshot_version("live")
    init_db()
    session = SessionLocal()
    try:
        payload = build_live_snapshot_payload()
        snapshot = create_snapshot(
            session,
            LiveWithOddsSnapshot,
            payload=payload,
            version=version,
            status="success",
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            activate=True,
        )
        return {
            "status": "success",
            "snapshot_version": snapshot.version,
            "items": len(payload.get("items", [])),
        }
    except Exception as e:
        logger.error("task_refresh_live_snapshot failed: %s", e, exc_info=True)
        session.rollback()
        record_snapshot_failure(
            session,
            LiveWithOddsSnapshot,
            version=version,
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            message=str(e),
        )
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@celery_app.task(name="task_refresh_results_and_bankroll_snapshot")
def task_refresh_results_and_bankroll_snapshot() -> TaskResult:
    started_at = _task_window()
    init_db()
    session = SessionLocal()
    results_version = build_snapshot_version("results")
    bankroll_version = build_snapshot_version("bankroll")
    try:
        results_payload = build_betting_results_payload(session)
        bankroll_payload = build_bankroll_summary_payload(session)
        results_snapshot = create_snapshot(
            session,
            BettingResultsSnapshot,
            payload=results_payload,
            version=results_version,
            status="success",
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            activate=True,
        )
        bankroll_snapshot = create_snapshot(
            session,
            BankrollSummarySnapshot,
            payload=bankroll_payload,
            version=bankroll_version,
            status="success",
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            activate=True,
        )
        return {
            "status": "success",
            "results_snapshot_version": results_snapshot.version,
            "bankroll_snapshot_version": bankroll_snapshot.version,
            "results_count": len(results_payload.get("items", [])),
            "active_bets_count": len(bankroll_payload.get("active_bets", [])),
        }
    except Exception as e:
        logger.error("task_refresh_results_and_bankroll_snapshot failed: %s", e, exc_info=True)
        session.rollback()
        record_snapshot_failure(
            session,
            BettingResultsSnapshot,
            version=results_version,
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            message=str(e),
        )
        record_snapshot_failure(
            session,
            BankrollSummarySnapshot,
            version=bankroll_version,
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            message=str(e),
        )
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@celery_app.task(name="task_refresh_rankings_snapshot")
def task_refresh_rankings_snapshot() -> TaskResult:
    started_at = _task_window()
    version = build_snapshot_version("rankings")
    init_db()
    session = SessionLocal()
    try:
        payload = build_power_rankings_payload()
        snapshot = create_snapshot(
            session,
            PowerRankingsSnapshot,
            payload=payload,
            version=version,
            status="success",
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            activate=True,
        )
        return {
            "status": "success",
            "snapshot_version": snapshot.version,
            "items": len(payload.get("items", [])),
        }
    except Exception as e:
        logger.error("task_refresh_rankings_snapshot failed: %s", e, exc_info=True)
        session.rollback()
        record_snapshot_failure(
            session,
            PowerRankingsSnapshot,
            version=version,
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            message=str(e),
        )
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@celery_app.task(name="task_refresh_homepage_manifest")
def task_refresh_homepage_manifest() -> TaskResult:
    started_at = _task_window()
    version = build_snapshot_version("homepage")
    init_db()
    session = SessionLocal()
    try:
        payload = build_homepage_manifest_payload(session)
        snapshot = create_snapshot(
            session,
            HomepageSnapshotManifest,
            payload=payload,
            version=version,
            status="success",
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            activate=True,
        )
        purge_cloudflare_cache(reason="task_refresh_homepage_manifest")
        return {
            "status": "success",
            "snapshot_version": snapshot.version,
        }
    except Exception as e:
        logger.error("task_refresh_homepage_manifest failed: %s", e, exc_info=True)
        session.rollback()
        record_snapshot_failure(
            session,
            HomepageSnapshotManifest,
            version=version,
            source_window_started_at=started_at,
            source_window_completed_at=utc_now(),
            message=str(e),
        )
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


def run_snapshot_refresh_after_settlement() -> dict[str, object]:
    results_bankroll = task_refresh_results_and_bankroll_snapshot.apply().get()
    task_refresh_upcoming_snapshot.apply().get()
    task_refresh_live_snapshot.apply().get()
    homepage = task_refresh_homepage_manifest.apply().get()
    return {
        "results_and_bankroll_snapshot": results_bankroll,
        "homepage_manifest": homepage,
    }


def _refresh_pipeline_acquire_slot(task_id: str) -> bool:
    existing = get_current_task_id()
    if not existing or existing == task_id:
        set_current_task_id(task_id)
        return True
    result = AsyncResult(existing, app=celery_app)
    state = (result.state or "PENDING").upper()
    if state in ("PENDING", "STARTED", "PROGRESS"):
        return False
    clear_current_task_id()
    set_current_task_id(task_id)
    return True


@celery_app.task(name="task_refresh_odds_pipeline", bind=True)
def task_refresh_odds_pipeline(self) -> TaskResult:
    task_id = self.request.id
    if not _refresh_pipeline_acquire_slot(task_id):
        return {
            "status": "skipped",
            "message": "Another refresh is already running",
            "progress": 0,
            "stage": "skipped",
        }
    try:
        self.update_state(state="PROGRESS", meta={"progress": 5, "stage": "queued"})

        self.update_state(
            state="PROGRESS",
            meta={"progress": 20, "stage": "refreshing_pandascore"},
        )
        pandascore_result = refresh_pandascore_upcoming()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 55, "stage": "refreshing_thunderpick"},
        )
        thunderpick_result = refresh_thunderpick_odds()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 80, "stage": "placing_bets"},
        )
        auto_bets_result = task_auto_place_bets()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 88, "stage": "refreshing_upcoming_snapshot"},
        )
        upcoming_snapshot_result = task_refresh_upcoming_snapshot()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 92, "stage": "refreshing_results_snapshot"},
        )
        results_snapshot_result = task_refresh_results_and_bankroll_snapshot()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 96, "stage": "refreshing_live_snapshot"},
        )
        live_snapshot_result = task_refresh_live_snapshot()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 97, "stage": "refreshing_homepage_manifest"},
        )
        manifest_result = task_refresh_homepage_manifest()

        self.update_state(
            state="PROGRESS",
            meta={"progress": 99, "stage": "finalizing"},
        )
        return {
            "status": "success",
            "message": "Manual refresh pipeline completed",
            "pandascore": pandascore_result,
            "thunderpick": thunderpick_result,
            "auto_bets": auto_bets_result,
            "upcoming_snapshot": upcoming_snapshot_result,
            "results_and_bankroll_snapshot": results_snapshot_result,
            "live_snapshot": live_snapshot_result,
            "homepage_manifest": manifest_result,
            "progress": 100,
            "stage": "completed",
        }
    except Exception as e:
        logger.error("task_refresh_odds_pipeline failed: %s", e, exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "progress": 100,
            "stage": "failed",
        }
    finally:
        clear_current_task_id()
        set_last_completed_at_now()


@celery_app.task(name="task_settle_bets")
def task_settle_bets() -> TaskResult:
    try:
        from betting.bet_manager import settle_completed_bets

        init_db()
        session = SessionLocal()
        try:
            summary = settle_completed_bets(session)
            refresh_out = run_snapshot_refresh_after_settlement()
            model_health = task_verify_model_health()
            return {
                "status": "success",
                "message": "Settlement completed",
                "results": [summary],
                "results_and_bankroll_snapshot": refresh_out["results_and_bankroll_snapshot"],
                "homepage_manifest": refresh_out["homepage_manifest"],
                "model_health": model_health,
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_settle_bets failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="ingest_lol_data")
def ingest_lol_data(file_path: str) -> TaskResult:
    if not os.path.exists(file_path):
        logger.error(
            "task ingest_lol_data failed: file_path=%s error=File not found",
            file_path,
        )
        return {"status": "error", "message": f"File {file_path} not found"}

    df = pd.read_csv(file_path, low_memory=False)
    df.columns = [
        c.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
        for c in df.columns
    ]

    if df.columns[0] in ["id", "gameid", "game_id"]:
        df = df.iloc[:, 1:]

    output = io.StringIO()
    df.to_csv(output, index=False, header=False)
    csv_content = output.getvalue()

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        columns = ", ".join(f'"{c}"' for c in df.columns)
        copy_sql = (
            f'COPY game_stats ({columns}) FROM STDIN WITH (FORMAT csv, DELIMITER \',\', NULL \'\')'
        )
        with cursor.copy(copy_sql) as copy:
            copy.write(csv_content)
        conn.commit()
        return {"status": "success", "rows": len(df)}
    except Exception as e:
        conn.rollback()
        logger.error(
            "task ingest_lol_data failed: file_path=%s error_type=%s error=%s",
            file_path,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


@celery_app.task(name="task_ingest_normalized")
def task_ingest_normalized(data_dir: str = "/data/matches") -> TaskResult:
    try:
        from scripts.ingest_all_matches import ingest_all

        results = ingest_all(data_dir)
        total_games = sum(r["games"] for r in results)
        total_players = sum(r["game_players"] for r in results)
        return {
            "status": "success",
            "total_games": total_games,
            "total_players": total_players,
            "files": results,
        }
    except Exception as e:
        logger.error("task_ingest_normalized failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_feature_engineering")
def task_feature_engineering() -> TaskResult:
    try:
        from ml.feature_engineer import compute_all_features

        init_db()
        session = SessionLocal()
        try:
            created = compute_all_features(session)
            return {"status": "success", "features_created": created}
        finally:
            session.close()
    except Exception as e:
        logger.error("task_feature_engineering failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_model_training")
def task_model_training() -> TaskResult:
    try:
        from ml.feature_engineer import load_feature_matrix
        from ml.model_registry import train_all_models, persist_model_runs

        init_db()
        session = SessionLocal()
        try:
            X, y, feature_names, metadata = load_feature_matrix(session)
            if len(y) == 0:
                return {"status": "error", "message": "No training data available"}

            results = train_all_models(X, y, metadata, feature_names)
            run_ids = persist_model_runs(session, results)
            promoted = next(
                (
                    {
                        "run_id": r.get("run_id"),
                        "model_type": r["model_type"],
                        "model_version": r["model_version"],
                    }
                    for r in results
                    if getattr(r.get("persisted_run"), "is_active", False)
                ),
                None,
            )
            return {
                "status": "success",
                "models_trained": len(results),
                "run_ids": run_ids,
                "best_model": next((r["model_type"] for r in results if r.get("is_active")), None),
                "promoted_model": promoted,
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_model_training failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_sync_rosters")
def task_sync_rosters() -> TaskResult:
    try:
        from services.pandascore import fetch_json_sync, get_token
        from entity_resolution.resolver import EntityResolver
        from entity_resolution.canonical_store import (
            get_all_teams,
            set_roster_entry,
            deactivate_roster,
        )

        init_db()
        session = SessionLocal()
        resolver = EntityResolver(session)
        token = get_token()
        synced = 0
        errors: list[dict[str, object]] = []

        try:
            teams = get_all_teams(session)
            teams_with_ps = [t for t in teams if t.pandascore_id is not None]
            logger.info("Syncing rosters for %d teams with PandaScore IDs", len(teams_with_ps))

            for team in teams_with_ps:
                try:
                    data = fetch_json_sync(
                        f"/teams/{team.pandascore_id}",
                        token=token,
                    )
                    if not isinstance(data, dict):
                        continue

                    players = data.get("players") or []
                    if not players:
                        continue

                    deactivate_roster(session, team.id)
                    for p in players:
                        p_name = p.get("name") or p.get("slug") or ""
                        if not p_name:
                            continue
                        p_role = (p.get("role") or "").lower()
                        p_ps_id = p.get("id")
                        p_nationality = p.get("nationality")
                        p_real_name = (p.get("first_name") or "") + " " + (p.get("last_name") or "")

                        player = resolver.resolve_player(
                            p_name, "pandascore",
                            pandascore_id=p_ps_id,
                            role=p_role,
                        )
                        if player:
                            if p_real_name.strip() and not player.real_name:
                                player.real_name = p_real_name.strip()
                            if p_nationality and not player.nationality:
                                player.nationality = p_nationality

                            set_roster_entry(
                                session, team.id, player.id,
                                role=p_role or "unknown",
                                source="pandascore",
                            )

                    session.commit()
                    synced += 1
                except Exception as e:
                    errors.append({"team": team.canonical_name, "error": str(e)})
                    logger.warning("Roster sync failed for %s: %s", team.canonical_name, e)

            return {
                "status": "success",
                "teams_synced": synced,
                "errors": errors,
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_sync_rosters failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_full_pipeline")
def task_full_pipeline(data_dir: str = "/data/matches") -> TaskResult:
    results: TaskResult = {}

    ingest_result = task_ingest_normalized(data_dir)
    results["ingest"] = ingest_result
    if ingest_result.get("status") != "success":
        return {"status": "error", "stage": "ingest", "results": results}

    fe_result = task_feature_engineering()
    results["features"] = fe_result
    if fe_result.get("status") != "success":
        return {"status": "error", "stage": "feature_engineering", "results": results}

    train_result = task_model_training()
    results["training"] = train_result
    results["snapshots"] = {
        "upcoming": task_refresh_upcoming_snapshot(),
        "live": task_refresh_live_snapshot(),
        "results_and_bankroll": task_refresh_results_and_bankroll_snapshot(),
        "rankings": task_refresh_rankings_snapshot(),
        "homepage": task_refresh_homepage_manifest(),
    }

    return {
        "status": "success" if train_result.get("status") == "success" else "partial",
        "results": results,
    }


OE_GOOGLE_DRIVE_FOLDER_ID = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"


def _download_oe_data_from_google_drive(data_dir: str) -> str | None:
    import shutil

    import gdown

    os.makedirs(data_dir, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{OE_GOOGLE_DRIVE_FOLDER_ID}"

    try:
        logger.info("task_refresh_data: downloading OE data from Google Drive folder %s", OE_GOOGLE_DRIVE_FOLDER_ID)
        out = gdown.download_folder(
            url=url,
            output=data_dir,
            quiet=True,
            use_cookies=False,
        )
        if not out:
            logger.error("task_refresh_data: gdown returned no files")
            return None

        data_path = Path(data_dir)
        pattern = "*_LoL_esports_match_data_from_OraclesElixir.csv"
        for csv_file in data_path.rglob(pattern):
            if csv_file.parent != data_path:
                dest = data_path / csv_file.name
                if dest != csv_file:
                    shutil.move(str(csv_file), str(dest))
                    logger.info("task_refresh_data: moved %s -> %s", csv_file.name, data_dir)

        count = len(list(data_path.glob(pattern)))
        logger.info("task_refresh_data: %d OE CSV(s) in %s", count, data_dir)
        return data_dir
    except Exception as e:
        logger.error("task_refresh_data: Google Drive download failed: %s", e, exc_info=True)
        return None


@celery_app.task(name="task_refresh_data")
def task_refresh_data() -> TaskResult:
    data_dir = os.environ.get("MATCH_DATA_DIR", "/data/matches")

    downloaded = _download_oe_data_from_google_drive(data_dir)
    if not downloaded:
        return {"status": "error", "stage": "download", "message": "Google Drive download failed"}

    ingest_result = task_ingest_normalized(data_dir)
    if ingest_result.get("status") != "success":
        return {"status": "error", "stage": "ingest", "results": ingest_result}

    fe_result = task_feature_engineering()
    if fe_result.get("status") != "success":
        return {"status": "error", "stage": "features", "results": fe_result}

    train_result = task_model_training()
    model_health = task_verify_model_health()
    snapshots = {
        "upcoming": task_refresh_upcoming_snapshot(),
        "live": task_refresh_live_snapshot(),
        "results_and_bankroll": task_refresh_results_and_bankroll_snapshot(),
        "rankings": task_refresh_rankings_snapshot(),
        "homepage": task_refresh_homepage_manifest(),
    }
    return {
        "status": "success" if train_result.get("status") == "success" else "partial",
        "downloaded": data_dir,
        "ingest": ingest_result,
        "features": fe_result,
        "training": train_result,
        "model_health": model_health,
        "snapshots": snapshots,
    }


@celery_app.task(name="task_verify_model_health")
def task_verify_model_health() -> TaskResult:
    try:
        from ml.model_manifest import read_model_manifest
        from ml.predictor_v2 import get_prediction_runtime_status

        init_db()
        session = SessionLocal()
        try:
            runtime_status = get_prediction_runtime_status(session)
            manifest = read_model_manifest() or {}
            active_model_id = runtime_status.get("active_model_id")
            has_active_model = active_model_id is not None
            return {
                "status": "success" if has_active_model else "error",
                "active_model_id": active_model_id,
                "active_model_version": runtime_status.get("active_model_version"),
                "active_model_path": runtime_status.get("active_model_path"),
                "manifest_run_id": manifest.get("source_run_id"),
                "manifest_version": manifest.get("model_version"),
                "game_data_row_count": runtime_status.get("game_data_row_count"),
                "message": "Active model is available" if has_active_model else "No active model is loadable",
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_verify_model_health failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@celery_app.task(name="task_check_completed_matches")
def task_check_completed_matches() -> TaskResult:
    try:
        from services.pandascore import get_token, fetch_json_sync
        from entity_resolution.resolver import EntityResolver
        from sqlalchemy import text as sql_text

        init_db()
        session = SessionLocal()
        try:
            token = get_token()
            past_matches = fetch_json_sync(
                "/lol/matches/past",
                params={"per_page": 50, "sort": "-scheduled_at"},
                token=token,
            )
            if not isinstance(past_matches, list):
                return {"status": "error", "message": "Unexpected PandaScore response"}

            resolver = EntityResolver(session)
            found_in_db = 0
            missing: list[dict[str, object]] = []

            for m in past_matches:
                opps = m.get("opponents") or []
                if len(opps) < 2:
                    continue

                team1_name = (opps[0].get("opponent") or {}).get("name", "")
                team2_name = (opps[1].get("opponent") or {}).get("name", "")
                ps_id1 = (opps[0].get("opponent") or {}).get("id")
                ps_id2 = (opps[1].get("opponent") or {}).get("id")
                acr1 = (opps[0].get("opponent") or {}).get("acronym")
                acr2 = (opps[1].get("opponent") or {}).get("acronym")

                team_a = resolver.resolve_team(
                    team1_name, "pandascore",
                    pandascore_id=ps_id1, abbreviation=acr1,
                )
                team_b = resolver.resolve_team(
                    team2_name, "pandascore",
                    pandascore_id=ps_id2, abbreviation=acr2,
                )

                if team_a and team_b:
                    scheduled = m.get("scheduled_at") or m.get("begin_at") or ""
                    recent_game = session.execute(sql_text("""
                        SELECT COUNT(*) FROM game
                        WHERE (blue_team_id = :a AND red_team_id = :b)
                           OR (blue_team_id = :b AND red_team_id = :a)
                        AND played_at >= NOW() - INTERVAL '3 days'
                    """), {"a": team_a.id, "b": team_b.id}).scalar()

                    if recent_game and recent_game > 0:
                        found_in_db += 1
                    else:
                        missing.append({
                            "match_id": m.get("id"),
                            "team1": team1_name,
                            "team2": team2_name,
                            "scheduled_at": scheduled,
                        })

            session.commit()
            return {
                "status": "success",
                "checked": len(past_matches),
                "found_in_db": found_in_db,
                "missing_count": len(missing),
                "missing": missing[:20],
            }
        finally:
            session.close()
    except Exception as e:
        logger.error("task_check_completed_matches failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}
