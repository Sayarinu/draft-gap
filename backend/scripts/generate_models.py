import os
from pathlib import Path

import pandas as pd

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.dirname(script_dir)
_data_dir = os.getenv("DATA_DIR")
if _data_dir is None:
    repo_root = os.path.dirname(backend_root)
    _data_dir = os.path.join(repo_root, "data")
if not os.path.isabs(_data_dir):
    _data_dir = os.path.abspath(_data_dir)
data_path = Path(_data_dir)
files = sorted(data_path.rglob("*.csv"))

if not files:
    print(f"No CSV files found under {data_path}!")
    exit(1)

all_columns = set()
for f in files:
    try:
        df = pd.read_csv(f, nrows=1)
    except Exception as e:
        print(f"Skip {f}: {e}")
        continue
    clean_cols = [
        c.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
        for c in df.columns
    ]
    all_columns.update(clean_cols)
print(f"Scanned {len(files)} CSVs, {len(all_columns)} unique columns.")


def _to_python_attr(col: str) -> str:
    s = col.replace("%", "_pct").replace("+", "_plus_")
    s = "".join(c if c.isalnum() or c == "_" else "_" for c in s).strip("_") or "col"
    if s and s[0].isdigit():
        s = "col_" + s
    if not s.isidentifier():
        s = "col_" + s
    return s

output_path = os.path.join(backend_root, "models.py")

with open(output_path, "w") as f:
    f.write("from database import Base\n")
    f.write("from sqlalchemy.orm import Mapped, mapped_column\n\n")
    f.write("class GameStat(Base):\n")
    f.write("    __tablename__ = 'game_stats'\n")
    f.write(
        "    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)\n"
    )

    for col in sorted(list(all_columns)):
        attr = _to_python_attr(col)
        f.write(f'    {attr}: Mapped[str] = mapped_column("{col}", nullable=True)\n')

print(f"Generated {output_path} with {len(all_columns)} columns.")
