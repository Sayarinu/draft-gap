
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, init_db
from ml.feature_engineer import compute_all_features, load_feature_matrix
from ml.model_registry import train_all_models, persist_model_runs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("train_model")


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        logger.info("Checking feature matrix...")
        X, y, feature_names, metadata = load_feature_matrix(session)

        if len(y) == 0:
            logger.info("No features found. Computing features first...")
            created = compute_all_features(session)
            logger.info("Computed %d features", created)
            X, y, feature_names, metadata = load_feature_matrix(session)

        if len(y) == 0:
            logger.error("No training data available. Run ingestion first.")
            return

        logger.info("Training on %d samples with %d features", len(y), len(feature_names))
        results = train_all_models(X, y, metadata, feature_names)
        run_ids = persist_model_runs(session, results)

        logger.info("=" * 60)
        for r in results:
            active = " [ACTIVE]" if r.get("is_active") else ""
            train_m = r.get("train_metrics", {})
            val_m = r.get("val_metrics", {})
            test_m = r.get("test_metrics", {})
            logger.info(
                "%s%s: train_acc=%.3f val_acc=%.3f test_acc=%.3f val_logloss=%.4f val_auc=%.3f",
                r["model_type"], active,
                train_m.get("accuracy", 0),
                val_m.get("accuracy", 0),
                test_m.get("accuracy", 0),
                val_m.get("log_loss", 999),
                val_m.get("roc_auc", 0),
            )
        logger.info("=" * 60)
        logger.info("Model run IDs: %s", run_ids)
    finally:
        session.close()


if __name__ == "__main__":
    main()
