import os

from celery import Celery
from celery.schedules import crontab

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if _DATABASE_URL and _DATABASE_URL.startswith("postgresql"):
    if _DATABASE_URL.startswith("postgresql://") and "+" not in _DATABASE_URL.split("://")[0]:
        _DATABASE_URL = _DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    CELERY_RESULT_BACKEND = "db+" + _DATABASE_URL
else:
    CELERY_RESULT_BACKEND = CELERY_BROKER_URL

celery_app = Celery("tasks", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

celery_app.conf.beat_schedule = {
    "refresh-odds-pipeline": {
        "task": "task_refresh_odds_pipeline",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "celery"},
    },
    "auto-place-bets": {
        "task": "task_auto_place_bets",
        "schedule": crontab(minute="5,20,35,50"),
        "options": {"queue": "celery"},
    },
    "settle-bets": {
        "task": "task_settle_bets",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "celery"},
    },
    "sync-rosters-daily": {
        "task": "task_sync_rosters",
        "schedule": crontab(hour=6, minute=0),
        "options": {"queue": "celery"},
    },
    "check-completed-matches": {
        "task": "task_check_completed_matches",
        "schedule": crontab(hour="*/6", minute=15),
        "options": {"queue": "celery"},
    },
    "refresh-data-daily": {
        "task": "task_refresh_data",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "celery"},
    },
}
celery_app.conf.beat_schedule_filename = "/cache/pandascore/celerybeat-schedule"

import tasks
