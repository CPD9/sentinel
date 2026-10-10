# SENTINEL API (`services/api/`)

The thin FastAPI layer between the web app and the pipeline. The contract is [`docs/API.md`](../../docs/API.md),
response bodies are the dataclasses in [`pipeline/schemas.py`](../../pipeline/schemas.py).

**Status: fixture mode only.** Every endpoint in API.md answers, serving the MOCK documents in
[`fixtures/`](../../fixtures/README.md). Real mode (uploads, `process_call()`, results from `out/` and
`artifacts/`, audio and snippets) comes with the pipeline milestone.

## Run

From the repo root (Python 3.11, same `.venv` as the pipeline):

```bash
uv pip install -r services/api/requirements.txt
SENTINEL_FIXTURES=1 python -m services.api          # http://127.0.0.1:8001, docs at /docs
```

Then the web app against it, in a second terminal:

```bash
cd web
cp .env.example .env.local      # then set NEXT_PUBLIC_DATA_MODE=api in .env.local
npm install && npm run dev      # http://127.0.0.1:3000; /api/* is proxied to 127.0.0.1:8001
```

Tests (skipped automatically when the API deps are missing):

```bash
pytest tests/test_api.py
```

## Files

| File | What it does |
|---|---|
| `main.py` | The app: error format, CORS, calls / documents / audio / quality / health endpoints |
| `events.py` | Server-Sent Events: per-call replay + live, global stream, `Last-Event-ID` resume, heartbeats |
| `settings.py` | Thresholds, keywords, rules (GET/PUT with validation) and `POST /settings/preview` |
| `deps.py` | Shared pieces: `ApiError`, the store, `checked()` (schema validation), `known_call()` |
| `store.py` | Where data comes from. `FixtureStore` today; an `ArtifactStore` with the same methods later |
| `__main__.py` | `python -m services.api` → uvicorn on 127.0.0.1 (port `API_PORT`, default 8001) |

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `SENTINEL_FIXTURES` | unset | `1` = serve `fixtures/`. Required for now; without it the API refuses to start |
| `API_PORT` | `8001` | Port (8000 stays free for the vLLM tunnel) |
| `SENTINEL_REPLAY_SCALE` | `0.1` | Fixture event replay pacing, as a fraction of the recorded gaps (0 = instant) |

## Fixture mode behaviour (MOCK)

- `GET /calls`, `/calls/{id}`, `/transcript`, `/trace`, `/analysis`, `/quality` serve the fixture files,
  validated against `pipeline/schemas.py` (a broken file → `500 internal` with the schema errors).
- `/calls/{id}/events` replays `<id>.events.json`, paced so the Processing view ticks. Calls without a log get a
  short synthesized log consistent with their row and result. `/events` sends only heartbeats.
- `POST /calls` → `409 conflict`. Audio and snippets → `404 not_available`.
- Settings start from MOCK defaults (same values as the web app's fixtures mode). PUT validates and keeps
  them **in memory only** (no `config/` files yet) and answers `n_calls: 0`, since nothing is re-run.
- `POST /settings/preview` re-applies the decide.py priority order to the cached rows with the new
  thresholds. It is a MOCK approximation: risk and confidence come from the row, not from re-running rules.
  Keyword hit counts are case-insensitive substring counts over the fixture transcripts.
