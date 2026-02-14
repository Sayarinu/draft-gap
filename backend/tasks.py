import io
import os

import pandas as pd
from database import engine
from worker import celery_app


@celery_app.task(name="ingest_lol_data")
def ingest_lol_data(file_path: str):
    if not os.path.exists(file_path):
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
    output.seek(0)

    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        columns = ", ".join(df.columns)
        cursor.copy_from(
            output, "game_stats", sep=",", null="", columns=tuple(df.columns)
        )
        conn.commit()
        return {"status": "success", "rows": len(df)}
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
