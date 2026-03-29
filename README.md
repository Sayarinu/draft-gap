# [Draft Gap](https://draft-gap.sayarin.xyz)

Draft Gap is a full-stack system for **predicting professional League of Legends match outcomes** and comparing model odds to bookmaker odds. It ingests historical match data, runs an ML pipeline, and serves predictions and live/upcoming match views through a single backend and UI.

---

## Solution approach

1. **Data** — Match and player-level stats come from **OraclesElixir** (yearly CSVs). You can use [pre-collected Oracle's Elixir data](https://www.dropbox.com/scl/fo/9hb9p0rqeimiqpbpk68uk/AIa_f8Qna95ALcBn-A69qjg?rlkey=6imm60dxj6srzhh7c016kx8ai&st=lv56j81r&dl=0), or supply your own. Upcoming and live fixtures, plus team/player metadata, come from the **PandaScore** API. **Betting** odds are scraped and cached for comparison.

2. **Entity resolution** — Teams, players, leagues, and champions are normalized into canonical entities (with aliases and fuzzy matching) so that OraclesElixir, PandaScore, and the betting source refer to the same teams and players. Resolution is persisted in PostgreSQL and cached in Redis.

3. **Features** — Rolling-window team stats (win rate, objectives, early-game gold/XP, etc.), head-to-head history, and league/patch context are computed from **past data only** to avoid leakage. Early-game stats are filled from player-level aggregates when team-level values are missing.

4. **Models** — The pipeline trains **Logistic Regression**, **XGBoost**, and an **MLP** on the feature matrix, evaluates them with temporal validation (train on regular season, validate on playoffs, test on internationals), and promotes the best model by a combined score (AUC, accuracy, log-loss). Predictions are clamped to reduce overconfident odds.

5. **API** — FastAPI exposes upcoming and live matches (from PandaScore) enriched with model odds and, when available, bookie odds. Predictions support BO1/BO3/BO5 and live series score (conditional odds). Pipeline steps (ingest, features, train, roster sync, data refresh) can be triggered via API or Celery Beat.

6. **UI** — React + TypeScript SPA (Vite) shows upcoming and live matches with model vs bookie odds, series format, and (for live) current series score. All match and odds data is fetched from the backend; no direct PandaScore or betting-source calls from the client.

---

## Tech stack

|Layer|Technology|Role|
|---|---|---|
|**Frontend**|Vite, React, TypeScript, Tailwind|SPA shell, client routing, theme tokens|
|**Backend**|FastAPI, Pydantic|REST API, validation, dependency injection|
|**Database**|PostgreSQL 18, SQLAlchemy 2 (ORM)|Normalized schema: games, teams, players, rosters, champions, features, model runs|
|**Queue**|Celery, Redis|Background tasks (ingest, feature compute, train, PandaScore/betting refresh)|
|**ML**|pandas, scikit-learn, XGBoost, PyTorch, SHAP|Feature engineering, training, evaluation, interpretability|
|**Infrastructure**|Docker, Docker Compose|API, worker, beat, Postgres, Redis, pgAdmin|

---

## Getting started

**Prerequisites:** Docker and Docker Compose. Optional: `PANDA_SCORE_KEY` for live/upcoming matches and roster sync.

1. **Configure** — Copy `.env.example` to root `.env` and set `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `DATABASE_URL`. Set `FRONTEND_URL`, `NEXT_PUBLIC_API_URL`, `VITE_API_URL`, and `FRONTEND_API_SECRET` for frontend-to-API calls. Add `PANDA_SCORE_KEY` for PandaScore-backed operations.

2. **Run** — From the repo root:

   ```bash
   docker compose up -d
   ```

   - API: <http://localhost:8000>
   - Frontend: <http://localhost:3000>
   - Docs: <http://localhost:8000/docs>

3. **Ingest and train** — Match data lives in the `match_data` volume (in containers at `/data/matches`). Either let the **bootstrap** run on first start (or the daily 4 AM job) download OraclesElixir from [Google Drive](https://drive.google.com/drive/folders/1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH) and run the pipeline, or place your own OE CSVs in `data/matches/` and set the compose volume for `/data` to that folder. Then:

   ```bash
   docker compose exec worker python scripts/ingest_all_matches.py --data-dir /data/matches
   docker compose exec worker python -c "
   from database import SessionLocal, init_db
   from ml.feature_engineer import compute_all_features
   init_db(); s = SessionLocal(); compute_all_features(s); s.close()
   "
   docker compose exec worker python scripts/train_model.py
   ```

   Or trigger the full pipeline via API: `POST /api/v1/ml/pipeline/full`.

4. **Backfill entities (optional)** — Populate canonical champions, roster history, and team/player metadata from existing DB and PandaScore:

   ```bash
   docker compose exec worker python scripts/backfill_entities.py
   ```

## Project layout

- **backend/** — FastAPI app, Celery tasks, entity resolution, ML (feature_engineer, model_registry, predictor_v2), scripts (ingest, train, backfill).
- **frontend/** — Vite React SPA, app shell (`index.html`, `src/main.tsx`, `src/App.tsx`), components (tables, filters), `lib/api` for backend calls.
- **data/matches/** — OraclesElixir yearly CSVs (mounted into containers).
- **backend/models/** — Runtime model artifacts directory. Keep the folder, but generated model binaries are not committed; populate it by training or copying deploy-time artifacts.
- **.cursor/rules/** — Project style and type-annotation rules (avoid `Any`; use TypedDict/Protocol/object where possible).

## Testing

Tests in Draft Gap are behavior-focused: they validate user-visible UI output and API-visible contract behavior from controlled inputs, rather than asserting implementation details line by line.

### Frontend

Frontend tests use `Vitest`, `Testing Library`, and `MSW`.

```bash
cd frontend
npm test
npm run test:run
npm run test:coverage
```

### Backend

Backend tests use `pytest` against a dedicated Postgres test database. External services such as PandaScore, Thunderpick, Celery, and Cloudflare are mocked at the boundary so the suite stays deterministic.

Create a test database first, for example:

```bash
createdb draftgap_test
```

Then run:

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/draftgap_test pytest
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/draftgap_test pytest --cov
```

If you are using the local Docker Postgres service from `docker compose`, make sure it is running before backend tests:

```bash
docker compose up -d db
```

### Recommended local verification

Before pushing substantial changes:

```bash
cd frontend && npm run test:run && npm run build
cd backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/draftgap_test pytest
```
