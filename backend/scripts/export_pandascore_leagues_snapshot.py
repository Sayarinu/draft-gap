
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from services.pandascore import fetch_all_lol_leagues_sync, save_json_to_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Export PandaScore leagues snapshot.")
    parser.add_argument(
        "--output",
        type=str,
        default="docs/pandascore_leagues_snapshot.json",
        help="Output JSON file path.",
    )
    args = parser.parse_args()

    leagues = fetch_all_lol_leagues_sync(per_page=100)
    output_path = Path(args.output)
    save_json_to_file(leagues, output_path)
    print(f"Saved {len(leagues)} leagues to {output_path}")


if __name__ == "__main__":
    main()
