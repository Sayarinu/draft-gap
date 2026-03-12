from __future__ import annotations

import os

from env_defaults import DEFAULTS, get_int, get_float, get_required

_torch_device: str | None = None


def get_device() -> str:
    global _torch_device
    if _torch_device is not None:
        return _torch_device

    raw = (get_required("ML_DEVICE") or str(DEFAULTS.get("ML_DEVICE", "cpu"))).strip().lower()
    if raw == "mps":
        try:
            import torch
            if torch.backends.mps.is_available():
                _torch_device = "mps"
            else:
                _torch_device = "cpu"
        except ImportError:
            _torch_device = "cpu"
    elif raw == "cuda":
        try:
            import torch
            _torch_device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            _torch_device = "cpu"
    else:
        _torch_device = "cpu"
    return _torch_device


def get_model_path() -> str:
    return get_required("ML_MODEL_PATH").strip() or str(DEFAULTS.get("ML_MODEL_PATH", "./models"))


def get_training_config() -> dict[str, int | float]:
    return {
        "epochs": get_int("ML_EPOCHS"),
        "batch_size": get_int("ML_BATCH_SIZE"),
        "lr": get_float("ML_LR"),
        "val_frac": get_float("ML_VAL_FRAC"),
    }
