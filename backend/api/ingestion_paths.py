from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

_SAFE_CSV_NAME = re.compile(r"^[A-Za-z0-9._-]{1,240}\.csv$")


def resolved_csv_path_under_data(file_name: str) -> str:
    stripped = file_name.strip()
    base = PurePosixPath(stripped).name
    if not base or base != stripped:
        raise HTTPException(status_code=400, detail="Invalid file name")
    if not _SAFE_CSV_NAME.fullmatch(base):
        raise HTTPException(status_code=400, detail="Invalid file name")
    root = Path("/data").resolve()
    full = (root / base).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file name") from None
    return str(full)
