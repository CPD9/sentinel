"""SENTINEL API: the endpoints the web app calls (docs/API.md).

A thin layer: every endpoint asks the store for a document, validates it against pipeline/schemas.py
and returns it. Errors always have the body {"error": <code>, "detail": <str | list[str]>}.

Start (binds 127.0.0.1 only):  SENTINEL_FIXTURES=1 python -m services.api
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pipeline import schemas

from . import events, feedback, settings
from .deps import ApiError, checked, known_call, log, side_doc, store
from .store import SNIPPET_NAME_RE

API_VERSION = "0.1.0"
# No CORS wildcard (docs/API.md): only the local web dev origin. The web app normally goes through
# its own /api proxy (web/next.config.ts), so CORS only matters for direct browser calls.
WEB_ORIGINS = ["http://127.0.0.1:3000", "http://localhost:3000"]


# --------------------------------------------------------------------------- app
app = FastAPI(title="SENTINEL API", version=API_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)


def _error(status: int, code: str, detail: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError) -> JSONResponse:
    return _error(e.status, e.code, e.detail)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, e: StarletteHTTPException) -> JSONResponse:
    # Unknown paths and wrong methods also use the standard error body.
    return _error(e.status_code, "not_found" if e.status_code == 404 else "invalid", str(e.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
    detail = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
    return _error(422, "invalid", detail)


@app.exception_handler(Exception)
async def _unexpected(_: Request, e: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return _error(500, "internal", f"{type(e).__name__}: {e}")


api = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- health
@api.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "llm_reachable": False,   # fixture mode never talks to an LLM
        "gpu_queue_length": 0,
        "versions": {"api": API_VERSION, "mode": store.mode},
    }


# --------------------------------------------------------------------------- calls
@api.get("/calls")
def list_calls(status: str | None = None, decision: str | None = None,
               criterion: str | None = None, variant: str | None = None) -> list[dict]:
    rows = [checked(r, schemas.CallListItem.validate, f"row {r.get('call_id')}") for r in store.list_calls()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if decision:
        rows = [r for r in rows if r.get("decision") == decision]
    if criterion:
        rows = [r for r in rows if criterion in r.get("criteria", [])]
    if variant:
        rows = [r for r in rows if r.get("variant") == variant]
    return rows


@api.post("/calls")
def upload_call() -> None:
    # Real uploads (store the .wav under a neutral id, enqueue process_call) come with the pipeline milestone.
    raise ApiError(409, "conflict", "Uploads are disabled in fixture mode (MOCK data only).")


@api.get("/calls/{call_id}")
def get_call(call_id: str):
    row = known_call(call_id)
    if row["status"] in ("queued", "processing"):
        # Not finished yet: answer 202 with the inbox row (the UI shows the processing timeline).
        return JSONResponse(status_code=202, content=checked(row, schemas.CallListItem.validate, call_id))
    result = store.get_result(call_id)
    if result is None:
        raise ApiError(404, "not_available", f"Result not available for {call_id}")
    return checked(result, schemas.validate_call_result, f"{call_id} result")


@api.get("/calls/{call_id}/transcript")
def get_transcript(call_id: str) -> dict:
    return side_doc(call_id, "transcript", schemas.Transcript.validate)


@api.get("/calls/{call_id}/trace")
def get_trace(call_id: str) -> dict:
    return side_doc(call_id, "trace", schemas.DecisionTrace.validate)


@api.get("/calls/{call_id}/analysis")
def get_analysis(call_id: str, feature_maps: int = 0) -> dict:
    # feature_maps=1 is a STRETCH goal (lazy computation); fixture mode just returns the stored artifact.
    return side_doc(call_id, "analysis", schemas.AnalysisArtifact.validate)


@api.get("/calls/{call_id}/audio")
def get_audio(call_id: str):
    known_call(call_id)
    if store.audio_path(call_id) is None:
        raise ApiError(404, "not_available", f"No audio for {call_id} (fixture mode has no audio)")
    raise ApiError(404, "not_available", "Audio serving arrives with the pipeline milestone")


@api.get("/calls/{call_id}/snippets/{name}")
def get_snippet(call_id: str, name: str):
    known_call(call_id)
    if not SNIPPET_NAME_RE.match(name) or ".." in name:
        raise ApiError(404, "not_found", f"Invalid snippet name {name!r}")
    if store.snippet_path(call_id, name) is None:
        raise ApiError(404, "not_available", f"Snippet {name} not available (fixture mode has no audio)")
    raise ApiError(404, "not_available", "Snippet serving arrives with the pipeline milestone")


# --------------------------------------------------------------------------- quality
@api.get("/quality")
def list_quality() -> list[dict]:
    return store.list_quality()


@api.get("/quality/{report_id}")
def get_quality(report_id: str) -> dict:
    report = store.get_quality(report_id)
    if report is None:
        raise ApiError(404, "not_found", f"Unknown report {report_id!r}")
    return checked(report, schemas.QualityReport.validate, f"report {report_id}")


app.include_router(api)
app.include_router(events.router)
app.include_router(settings.router)
app.include_router(feedback.router)
