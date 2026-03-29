from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from ml.model_manifest import get_model_dir, write_model_manifest

logger = logging.getLogger(__name__)


class _ClassifierWithPredictProba(Protocol):

    def predict_proba(self, X: np.ndarray) -> np.ndarray: ...


def _eval_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float]:
    y_pred = (y_prob >= 0.5).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "log_loss": float(log_loss(y_true, y_prob, labels=[0, 1])),
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
    else:
        metrics["roc_auc"] = 0.5
    return metrics


def split_data(
    X: np.ndarray,
    y: np.ndarray,
    metadata: pd.DataFrame,
    feature_names: list[str],
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    international_slugs = {"worlds", "msi", "ewc", "fst"}

    is_intl = metadata["league_slug"].str.lower().isin(international_slugs)
    is_playoff = metadata["playoffs"].astype(bool) & ~is_intl

    train_mask = ~is_intl & ~is_playoff
    val_mask = is_playoff
    test_mask = is_intl

    if train_mask.sum() == 0:
        train_mask = np.ones(len(y), dtype=bool)
        val_mask = np.zeros(len(y), dtype=bool)
        test_mask = np.zeros(len(y), dtype=bool)

    return {
        "train": (X[train_mask], y[train_mask]),
        "val": (X[val_mask], y[val_mask]),
        "test": (X[test_mask], y[test_mask]),
    }


def train_logistic_regression(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feature_names: list[str],
) -> tuple[_ClassifierWithPredictProba, StandardScaler, dict[str, object]]:
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)

    model = LogisticRegression(
        max_iter=1000, C=0.1, solver="lbfgs", random_state=42,
    )
    model.fit(X_scaled, y_train)

    config = {"type": "logistic_regression", "C": 1.0, "max_iter": 1000}
    return model, scaler, config


def predict_logistic(
    model: _ClassifierWithPredictProba, scaler: StandardScaler, X: np.ndarray
) -> np.ndarray:
    return model.predict_proba(scaler.transform(X))[:, 1]


def save_logistic(
    model: _ClassifierWithPredictProba, scaler: StandardScaler, feature_names: list[str], path: Path
) -> None:
    joblib.dump({"model": model, "scaler": scaler, "feature_names": feature_names}, path)


def load_logistic(path: Path) -> tuple[_ClassifierWithPredictProba, StandardScaler, list[str]]:
    data = joblib.load(path)
    return data["model"], data["scaler"], data["feature_names"]


def train_xgboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feature_names: list[str],
    X_val: np.ndarray | None = None,
    y_val: np.ndarray | None = None,
) -> tuple[_ClassifierWithPredictProba, dict[str, object]]:
    import xgboost as xgb

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 4,
        "learning_rate": 0.03,
        "subsample": 0.75,
        "colsample_bytree": 0.7,
        "min_child_weight": 10,
        "reg_alpha": 0.1,
        "reg_lambda": 1.5,
        "seed": 42,
    }

    evals = [(dtrain, "train")]
    if X_val is not None and y_val is not None and len(y_val) > 0:
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)
        evals.append((dval, "val"))

    model = xgb.train(
        params, dtrain, num_boost_round=500, evals=evals,
        early_stopping_rounds=50, verbose_eval=False,
    )

    config = {"type": "xgboost", **params, "num_boost_round": model.best_iteration + 1}
    return model, config


def predict_xgboost(
    model: _ClassifierWithPredictProba, X: np.ndarray, feature_names: list[str]
) -> np.ndarray:
    import xgboost as xgb
    dmat = xgb.DMatrix(X, feature_names=feature_names)
    return model.predict(dmat)


def save_xgboost(
    model: _ClassifierWithPredictProba, feature_names: list[str], path: Path
) -> None:
    model.save_model(str(path.with_suffix(".xgb")))
    joblib.dump({"feature_names": feature_names}, path.with_suffix(".meta"))


def load_xgboost(path: Path) -> tuple[_ClassifierWithPredictProba, list[str]]:
    import xgboost as xgb
    model = xgb.Booster()
    model.load_model(str(path.with_suffix(".xgb")))
    meta = joblib.load(path.with_suffix(".meta"))
    return model, meta["feature_names"]


def train_mlp(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feature_names: list[str],
    X_val: np.ndarray | None = None,
    y_val: np.ndarray | None = None,
    epochs: int = 200,
    batch_size: int = 256,
    lr: float = 0.001,
) -> tuple[_ClassifierWithPredictProba, StandardScaler, dict[str, object]]:
    import torch
    import torch.nn as nn
    from ml.model import WinProbabilityMLP

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)

    input_dim = X_scaled.shape[1]
    model = WinProbabilityMLP(input_dim=input_dim, hidden=(128, 64, 32))

    device_name = os.environ.get("ML_DEVICE", "cpu")
    device = torch.device(device_name if device_name != "mps" or torch.backends.mps.is_available() else "cpu")
    model.to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.BCELoss()
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)

    X_t = torch.from_numpy(X_scaled).float()
    y_t = torch.from_numpy(y_train).float()

    best_val_loss = float("inf")
    patience_counter = 0
    best_state = None

    for epoch in range(epochs):
        model.train()
        indices = torch.randperm(len(X_t))
        epoch_loss = 0.0
        n_batches = 0

        for start in range(0, len(X_t), batch_size):
            batch_idx = indices[start:start + batch_size]
            xb = X_t[batch_idx].to(device)
            yb = y_t[batch_idx].to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1

        avg_loss = epoch_loss / max(n_batches, 1)

        if X_val is not None and len(X_val) > 0:
            model.eval()
            with torch.no_grad():
                X_val_t = torch.from_numpy(scaler.transform(X_val)).float().to(device)
                val_pred = model(X_val_t)
                val_loss = criterion(val_pred, torch.from_numpy(y_val).float().to(device)).item()
            scheduler.step(val_loss)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1

            if patience_counter >= 25:
                logger.info("MLP early stopping at epoch %d", epoch)
                break
        else:
            scheduler.step(avg_loss)

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    config = {"type": "mlp", "hidden": [128, 64, 32], "epochs": epoch + 1, "lr": lr, "batch_size": batch_size}
    return model, scaler, config


def predict_mlp(
    model: _ClassifierWithPredictProba, scaler: StandardScaler, X: np.ndarray
) -> np.ndarray:
    import torch
    model.eval()
    device = next(model.parameters()).device
    X_scaled = scaler.transform(X)
    with torch.no_grad():
        X_t = torch.from_numpy(X_scaled).float().to(device)
        return model(X_t).cpu().numpy()


def save_mlp(
    model: _ClassifierWithPredictProba, scaler: StandardScaler, feature_names: list[str], path: Path
) -> None:
    import torch
    torch.save({
        "state_dict": model.state_dict(),
        "input_dim": len(feature_names),
        "hidden": (128, 64, 32),
        "feature_names": feature_names,
    }, path.with_suffix(".pt"))
    joblib.dump({"scaler": scaler}, path.with_suffix(".scaler"))


def load_mlp(path: Path) -> tuple[_ClassifierWithPredictProba, StandardScaler, list[str]]:
    import torch
    from ml.model import WinProbabilityMLP

    state = torch.load(path.with_suffix(".pt"), map_location="cpu", weights_only=False)
    model = WinProbabilityMLP(input_dim=state["input_dim"], hidden=state.get("hidden", (128, 64, 32)))
    model.load_state_dict(state["state_dict"])
    model.eval()

    scaler_data = joblib.load(path.with_suffix(".scaler"))
    return model, scaler_data["scaler"], state["feature_names"]


def train_all_models(
    X: np.ndarray,
    y: np.ndarray,
    metadata: pd.DataFrame,
    feature_names: list[str],
) -> list[dict[str, object]]:
    model_dir = get_model_dir()
    splits = split_data(X, y, metadata, feature_names)
    X_train, y_train = splits["train"]
    X_val, y_val = splits["val"]
    X_test, y_test = splits["test"]

    logger.info(
        "Data split: train=%d, val=%d, test=%d, features=%d",
        len(y_train), len(y_val), len(y_test), len(feature_names),
    )

    results: list[dict[str, object]] = []
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger.info("Training Logistic Regression...")
    t0 = time.time()
    lr_model, lr_scaler, lr_config = train_logistic_regression(X_train, y_train, feature_names)
    lr_path = model_dir / f"logistic_{version}"
    save_logistic(lr_model, lr_scaler, feature_names, lr_path)

    lr_train_pred = predict_logistic(lr_model, lr_scaler, X_train)
    lr_result = {
        "model_type": "logistic_regression",
        "model_version": version,
        "artifact_path": str(lr_path),
        "config": lr_config,
        "feature_names": feature_names,
        "train_metrics": _eval_metrics(y_train, lr_train_pred),
        "train_samples": len(y_train),
    }
    if len(y_val) > 0:
        lr_val_pred = predict_logistic(lr_model, lr_scaler, X_val)
        lr_result["val_metrics"] = _eval_metrics(y_val, lr_val_pred)
        lr_result["val_samples"] = len(y_val)
    if len(y_test) > 0:
        lr_test_pred = predict_logistic(lr_model, lr_scaler, X_test)
        lr_result["test_metrics"] = _eval_metrics(y_test, lr_test_pred)
        lr_result["test_samples"] = len(y_test)
    logger.info("  LR done in %.1fs — train_acc=%.3f", time.time() - t0, lr_result["train_metrics"]["accuracy"])
    results.append(lr_result)

    logger.info("Training XGBoost...")
    t0 = time.time()
    xgb_model, xgb_config = train_xgboost(X_train, y_train, feature_names, X_val, y_val)
    xgb_path = model_dir / f"xgboost_{version}"
    save_xgboost(xgb_model, feature_names, xgb_path)

    xgb_train_pred = predict_xgboost(xgb_model, X_train, feature_names)
    xgb_result = {
        "model_type": "xgboost",
        "model_version": version,
        "artifact_path": str(xgb_path),
        "config": xgb_config,
        "feature_names": feature_names,
        "train_metrics": _eval_metrics(y_train, xgb_train_pred),
        "train_samples": len(y_train),
    }
    if len(y_val) > 0:
        xgb_val_pred = predict_xgboost(xgb_model, X_val, feature_names)
        xgb_result["val_metrics"] = _eval_metrics(y_val, xgb_val_pred)
        xgb_result["val_samples"] = len(y_val)
    if len(y_test) > 0:
        xgb_test_pred = predict_xgboost(xgb_model, X_test, feature_names)
        xgb_result["test_metrics"] = _eval_metrics(y_test, xgb_test_pred)
        xgb_result["test_samples"] = len(y_test)
    logger.info("  XGB done in %.1fs — train_acc=%.3f", time.time() - t0, xgb_result["train_metrics"]["accuracy"])
    results.append(xgb_result)

    logger.info("Training MLP...")
    t0 = time.time()
    mlp_model, mlp_scaler, mlp_config = train_mlp(X_train, y_train, feature_names, X_val, y_val)
    mlp_path = model_dir / f"mlp_{version}"
    save_mlp(mlp_model, mlp_scaler, feature_names, mlp_path)

    mlp_train_pred = predict_mlp(mlp_model, mlp_scaler, X_train)
    mlp_result = {
        "model_type": "mlp",
        "model_version": version,
        "artifact_path": str(mlp_path),
        "config": mlp_config,
        "feature_names": feature_names,
        "train_metrics": _eval_metrics(y_train, mlp_train_pred),
        "train_samples": len(y_train),
    }
    if len(y_val) > 0:
        mlp_val_pred = predict_mlp(mlp_model, mlp_scaler, X_val)
        mlp_result["val_metrics"] = _eval_metrics(y_val, mlp_val_pred)
        mlp_result["val_samples"] = len(y_val)
    if len(y_test) > 0:
        mlp_test_pred = predict_mlp(mlp_model, mlp_scaler, X_test)
        mlp_result["test_metrics"] = _eval_metrics(y_test, mlp_test_pred)
        mlp_result["test_samples"] = len(y_test)
    logger.info("  MLP done in %.1fs — train_acc=%.3f", time.time() - t0, mlp_result["train_metrics"]["accuracy"])
    results.append(mlp_result)

    def _selection_score(r: dict[str, object]) -> float:
        val_m = r.get("val_metrics", r["train_metrics"])
        test_m = r.get("test_metrics", {})
        val_auc = val_m.get("roc_auc", 0.5)
        test_acc = test_m.get("accuracy", 0.5)
        val_logloss = val_m.get("log_loss", 0.7)
        return (val_auc * 0.4) + (test_acc * 0.4) - (val_logloss * 0.2)

    best = max(results, key=_selection_score)
    best["is_active"] = True
    for result in results:
        val_metrics = result.get("val_metrics", result["train_metrics"])
        test_metrics = result.get("test_metrics", {})
        result["promotion_metrics"] = {
            "selection_score": _selection_score(result),
            "validation_log_loss": float(val_metrics.get("log_loss", 0.0)),
            "validation_roc_auc": float(val_metrics.get("roc_auc", 0.5)),
            "test_log_loss": float(test_metrics.get("log_loss", 0.0)) if test_metrics else None,
            "test_roc_auc": float(test_metrics.get("roc_auc", 0.5)) if test_metrics else None,
        }
    val_m = best.get("val_metrics", best["train_metrics"])
    logger.info(
        "Best model: %s (val_auc=%.4f, val_log_loss=%.4f)",
        best["model_type"], val_m.get("roc_auc", 0), val_m.get("log_loss", 0),
    )

    return results


def _run_selection_score(run: object) -> float:
    val_auc = float(getattr(run, "val_roc_auc", None) or getattr(run, "train_roc_auc", None) or 0.5)
    test_acc = float(getattr(run, "test_accuracy", None) or getattr(run, "val_accuracy", None) or 0.5)
    val_logloss = float(getattr(run, "val_log_loss", None) or getattr(run, "train_log_loss", None) or 0.7)
    return (val_auc * 0.4) + (test_acc * 0.4) - (val_logloss * 0.2)


def _candidate_selection_score(result: dict[str, object]) -> float:
    promotion_metrics = result.get("promotion_metrics", {})
    if isinstance(promotion_metrics, dict) and "selection_score" in promotion_metrics:
        return float(promotion_metrics["selection_score"])
    val_metrics = result.get("val_metrics", result.get("train_metrics", {}))
    test_metrics = result.get("test_metrics", {})
    return (
        float(val_metrics.get("roc_auc", 0.5)) * 0.4
        + float(test_metrics.get("accuracy", 0.5)) * 0.4
        - float(val_metrics.get("log_loss", 0.7)) * 0.2
    )


def _candidate_beats_active(
    candidate: dict[str, object],
    current_active: object | None,
) -> bool:
    if current_active is None:
        return True

    candidate_val = candidate.get("val_metrics", candidate.get("train_metrics", {}))
    candidate_test = candidate.get("test_metrics", {})
    candidate_auc = float(candidate_val.get("roc_auc", 0.5))
    candidate_log_loss = float(candidate_val.get("log_loss", 0.7))
    candidate_test_auc = float(candidate_test.get("roc_auc", candidate_auc))
    candidate_test_log_loss = float(candidate_test.get("log_loss", candidate_log_loss))
    candidate_score = _candidate_selection_score(candidate)

    current_auc = float(getattr(current_active, "val_roc_auc", None) or getattr(current_active, "train_roc_auc", None) or 0.5)
    current_log_loss = float(getattr(current_active, "val_log_loss", None) or getattr(current_active, "train_log_loss", None) or 0.7)
    current_test_auc = float(getattr(current_active, "test_roc_auc", None) or current_auc)
    current_test_log_loss = float(getattr(current_active, "test_log_loss", None) or current_log_loss)
    current_score = _run_selection_score(current_active)

    score_improved = candidate_score >= current_score + 0.002
    auc_not_worse = candidate_auc >= current_auc - 0.002 and candidate_test_auc >= current_test_auc - 0.01
    log_loss_not_worse = (
        candidate_log_loss <= current_log_loss + 0.01
        and candidate_test_log_loss <= current_test_log_loss + 0.02
    )
    primary_metric_improved = (
        candidate_auc >= current_auc + 0.002
        or candidate_log_loss <= current_log_loss - 0.005
    )
    return score_improved and auc_not_worse and log_loss_not_worse and primary_metric_improved


def persist_model_runs(
    session: Session, results: list[dict[str, object]]
) -> list[int]:
    from models_ml import MLModelRun

    run_ids: list[int] = []
    current_active = (
        session.query(MLModelRun)
        .filter(MLModelRun.is_active.is_(True))
        .order_by(MLModelRun.created_at.desc())
        .first()
    )

    for r in results:
        train_m = r.get("train_metrics", {})
        val_m = r.get("val_metrics", {})
        test_m = r.get("test_metrics", {})

        run = MLModelRun(
            model_type=r["model_type"],
            model_version=r["model_version"],
            artifact_path=r["artifact_path"],
            is_active=False,
            train_accuracy=train_m.get("accuracy"),
            val_accuracy=val_m.get("accuracy"),
            test_accuracy=test_m.get("accuracy"),
            train_log_loss=train_m.get("log_loss"),
            val_log_loss=val_m.get("log_loss"),
            test_log_loss=test_m.get("log_loss"),
            train_roc_auc=train_m.get("roc_auc"),
            val_roc_auc=val_m.get("roc_auc"),
            test_roc_auc=test_m.get("roc_auc"),
            train_samples=r.get("train_samples"),
            val_samples=r.get("val_samples"),
            test_samples=r.get("test_samples"),
            feature_names_json=json.dumps(r.get("feature_names", [])),
            config_json=json.dumps(r.get("config", {})),
        )
        session.add(run)
        session.flush()
        run_ids.append(run.id)
        r["run_id"] = run.id
        r["persisted_run"] = run

    candidate = max(results, key=_candidate_selection_score) if results else None
    promoted_run = None
    if candidate is not None:
        candidate_run = candidate.get("persisted_run")
        if candidate_run is not None and _candidate_beats_active(candidate, current_active):
            session.query(MLModelRun).filter(MLModelRun.is_active.is_(True)).update(
                {MLModelRun.is_active: False},
                synchronize_session=False,
            )
            candidate_run.is_active = True
            promoted_run = candidate_run
        elif current_active is not None:
            current_active.is_active = True

    session.commit()
    if promoted_run is not None:
        write_model_manifest(
            source_run_id=promoted_run.id,
            model_type=promoted_run.model_type,
            model_version=promoted_run.model_version,
            artifact_path=promoted_run.artifact_path,
            trained_at=getattr(promoted_run, "created_at", None) or datetime.now(timezone.utc),
        )
    try:
        from ml.predictor_v2 import clear_prediction_caches
        clear_prediction_caches()
    except Exception:
        logger.debug("Could not clear prediction caches after persisting model runs", exc_info=True)

    if promoted_run is not None:
        logger.info(
            "Promoted model run_id=%s type=%s version=%s",
            promoted_run.id,
            promoted_run.model_type,
            promoted_run.model_version,
        )
    elif candidate is not None and current_active is not None:
        logger.info(
            "Retained active model run_id=%s version=%s after candidate comparison",
            current_active.id,
            current_active.model_version,
        )
    return run_ids
