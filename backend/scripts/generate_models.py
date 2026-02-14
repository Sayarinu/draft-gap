import glob
import os

import pandas as pd

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.dirname(script_dir)

DATA_PATH = "/data/*.csv"
files = glob.glob(DATA_PATH)

if not files:
    print(f"No CSV files found in {DATA_PATH}!")
    exit()

all_columns = set()
for f in files:
    print(f"Scanning {f}...")
    df = pd.read_csv(f, nrows=1)
    clean_cols = [
        c.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
        for c in df.columns
    ]
    all_columns.update(clean_cols)

output_path = os.path.join(backend_root, "models.py")

with open(output_path, "w") as f:
    f.write("from sqlalchemy.orm import Mapped, mapped_column\n")
    f.write("from .database import Base\n\n")
    f.write("class GameStat(Base):\n")
    f.write("    __tablename__ = 'game_stats'\n")
    f.write(
        "    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)\n"
    )

    for col in sorted(list(all_columns)):
        f.write(f"    {col}: Mapped[str] = mapped_column(nullable=True)\n")

print(f"Generated {output_path} with {len(all_columns)} columns.")
