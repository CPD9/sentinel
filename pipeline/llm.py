"""Minimal OpenAI-compatible chat client for our self-hosted vLLM (stdlib only) plus a disk cache.

The endpoint is only ever `LLM_BASE_URL` (e.g. http://127.0.0.1:8000/v1 through the SSH tunnel).
No cloud inference APIs. Temperature 0 is not a determinism guarantee; the cache is.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_VERSION = f"python-{platform.python_version()}/llm-client-1"


class LLMError(RuntimeError):
    pass


def load_env(path: Path = REPO_ROOT / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding variables already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _request(url: str, payload: dict | None, timeout: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="GET" if payload is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')[:500]}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise LLMError(f"cannot reach {url}: {e}") from e


class OpenAICompatClient:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model = model
        self.model_revision: str | None = None

    def probe(self) -> dict:
        """GET /models: confirms the endpoint is up and resolves model id + revision (vLLM `root`)."""
        listing = _request(f"{self.base_url}/models", None, timeout=10)
        models = listing.get("data", [])
        if not models:
            raise LLMError(f"{self.base_url}/models lists no models")
        chosen = next((m for m in models if m.get("id") == self.model), None) if self.model else models[0]
        if chosen is None:
            raise LLMError(f"model {self.model!r} not served; available: {[m.get('id') for m in models]}")
        self.model = chosen["id"]
        self.model_revision = chosen.get("root") or chosen.get("id")
        return chosen

    def chat(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,
             json_schema: dict | None = None) -> str:
        payload = {"model": self.model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens}
        if json_schema is not None:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "answer", "schema": json_schema}}
        try:
            out = _request(f"{self.base_url}/chat/completions", payload, self.timeout)
        except LLMError as e:
            if json_schema is None or "HTTP 400" not in str(e):
                raise
            # older vLLM without json_schema support: retry unconstrained, the caller parses defensively
            payload.pop("response_format")
            out = _request(f"{self.base_url}/chat/completions", payload, self.timeout)
        try:
            return out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response shape: {str(out)[:300]}") from e


def from_env() -> OpenAICompatClient:
    load_env()
    base = os.environ.get("LLM_BASE_URL")
    if not base:
        raise LLMError("LLM_BASE_URL is not set (.env or environment)")
    return OpenAICompatClient(base, os.environ.get("LLM_MODEL") or None)


# --------------------------------------------------------------------------- cache

class DiskCache:
    """JSON files keyed by sha256 of the canonical request (content + model + prompt + runtime)."""

    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def key(obj: dict) -> str:
        return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def put(self, key: str, value: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)


def extraction_cache_key(segments: list[dict], model_id: str, model_revision: str, prompt_version: str) -> str:
    """Cache key of one fact-extraction request: transcript content + model id/revision + prompt version + runtime.

    `segments` are {id, speaker, text} dicts. Keyword hits and every config/ file are deliberately NOT inputs, so
    editing keywords.json, rules.yaml or thresholds.json never invalidates cached extractions. Provisional until
    pipeline/extract.py (M4) adopts it.
    """
    return DiskCache.key({
        "step": "extract",
        "segments": [{"id": s["id"], "speaker": s["speaker"], "text": s["text"]} for s in segments],
        "model_id": model_id, "model_revision": model_revision, "prompt_version": prompt_version,
        "runtime": RUNTIME_VERSION,
    })
