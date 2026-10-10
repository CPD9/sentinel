"""OpenAI-compatible chat client with a provider registry, a policy gate and honest metrics (stdlib only,
PyYAML is imported lazily to read config/providers.yaml), plus a disk cache.

Providers live in config/providers.yaml (env var NAMES only, no secrets). The default is the self-hosted vLLM
(`apertus_aws`, `LLM_BASE_URL`, usually http://127.0.0.1:8000/v1 through the SSH tunnel). A provider with
`self_hosted: false` is refused BEFORE any network call unless `SENTINEL_ALLOW_REMOTE_LLM=fictional_data_only` is
set in the process environment and the model is on that provider's open-weight allowlist.
Keys are read from os.environ on every request; they are never stored on the client, logged, put in error text,
cache keys, metrics or traces. Temperature 0 is not a determinism guarantee; the cache is.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import platform
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_FILE = REPO_ROOT / "config" / "providers.yaml"
RUNTIME_VERSION = f"python-{platform.python_version()}/llm-client-2"

ALLOW_REMOTE_ENV = "SENTINEL_ALLOW_REMOTE_LLM"
ALLOW_REMOTE_VALUE = "fictional_data_only"
PROVIDER_ENV = "SENTINEL_LLM_PROVIDER"
MODEL_ENV = "SENTINEL_LLM_MODEL"       # model for the selected provider when it has no model_env (remote ones)


class LLMError(RuntimeError):
    pass


class ProviderNotPermitted(LLMError):
    """The policy gate refused a remote provider or model. Raised before any network call."""


class HTTPStatusError(LLMError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _Unreachable(LLMError):
    """Could not connect at all: a plain retry would fail the same way."""


class _StreamFailed(LLMError):
    """The streamed reply was unusable (empty, malformed, cut off): worth one plain retry."""


# --------------------------------------------------------------------------- env

# The remote opt-in must be a conscious per-process choice, so a stale line in .env can never enable it.
_NEVER_FROM_DOTENV = {ALLOW_REMOTE_ENV}


def load_env(path: Path = REPO_ROOT / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding variables already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key = key.strip()
        if key in _NEVER_FROM_DOTENV:
            continue
        os.environ.setdefault(key, value.strip().strip("'\""))


# --------------------------------------------------------------------------- registry

_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_PLACEHOLDER = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")
# Request fields the client owns. A provider's extra_body may add vendor options but never set these, so it
# cannot swap the gated model or the constrained-output schema.
RESERVED_BODY_KEYS = frozenset({
    "model", "messages", "temperature", "max_tokens", "max_completion_tokens", "response_format", "stream",
    "stream_options", "n", "tools", "tool_choice", "functions", "function_call",
    # OpenRouter fallback / routing fields that can select a different model than the one the gate checked
    "models", "route", "preset"})
# A remote provider's extra_body may carry only these vendor options (the gate cannot vet anything else).
REMOTE_EXTRA_BODY_KEYS = frozenset({"provider", "usage"})
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SPEC_KEYS = {"base_url", "base_url_env", "model_env", "key_env", "self_hosted", "region", "allowed_models",
              "extra_body"}


@dataclass(frozen=True)
class ProviderSpec:
    """Configuration of one provider. Holds env var NAMES only, never values."""
    name: str
    base_url: str | None = None          # may contain {ENV_NAME} placeholders
    base_url_env: str | None = None
    model_env: str | None = None
    key_env: str | None = None
    self_hosted: bool = True
    region: str | None = None
    allowed_models: tuple[str, ...] = ()
    extra_body: dict = field(default_factory=dict)

    def resolve_base_url(self) -> str:
        if self.base_url_env:
            value = os.environ.get(self.base_url_env)
            if not value:
                raise LLMError(f"{self.base_url_env} is not set (.env or environment)")
            return value.rstrip("/")

        def sub(m: re.Match) -> str:
            value = os.environ.get(m.group(1))
            if not value:
                raise LLMError(f"{m.group(1)} is not set (.env or environment), needed for provider {self.name!r}")
            return value
        return _PLACEHOLDER.sub(sub, self.base_url or "").rstrip("/")


def parse_providers(doc: dict) -> tuple[str, dict[str, ProviderSpec]]:
    """Validate a providers document. Returns (default provider name, specs by name)."""
    errs: list[str] = []
    raw = doc.get("providers")
    if not isinstance(raw, dict) or not raw:
        raise LLMError("providers.yaml: 'providers' must be a non-empty mapping")
    specs: dict[str, ProviderSpec] = {}
    for name, p in raw.items():
        if not isinstance(p, dict):
            errs.append(f"{name}: must be a mapping")
            continue
        errs += [f"{name}: unknown key {k!r}" for k in p if k not in _SPEC_KEYS]
        errs += [f"{name}.{k} must be an env var name (UPPER_SNAKE), not a value" for k in p
                 if k.endswith("_env") and not (isinstance(p[k], str) and _ENV_NAME.fullmatch(p[k]))]
        if (p.get("base_url") is None) == (p.get("base_url_env") is None):
            errs.append(f"{name}: set exactly one of base_url / base_url_env")
        hosted = p.get("self_hosted")
        if not isinstance(hosted, bool):
            errs.append(f"{name}.self_hosted must be true or false")
        allowed = p.get("allowed_models", [])
        if not (isinstance(allowed, list) and all(isinstance(m, str) and m for m in allowed)):
            errs.append(f"{name}.allowed_models must be a list of model ids")
            allowed = []
        extra = p.get("extra_body", {})
        if not isinstance(extra, dict):
            errs.append(f"{name}.extra_body must be a mapping")
            extra = {}
        errs += [f"{name}.extra_body may not set {k!r} (reserved request field)" for k in extra
                 if k in RESERVED_BODY_KEYS]
        if hosted is False:
            errs += [f"{name}.extra_body key {k!r} is not allowed for a remote provider "
                     f"(allowed: {sorted(REMOTE_EXTRA_BODY_KEYS)})" for k in extra
                     if k not in RESERVED_BODY_KEYS and k not in REMOTE_EXTRA_BODY_KEYS]
        if hosted is False:
            if not p.get("key_env"):
                errs.append(f"{name}: a remote provider needs key_env")
            if not allowed:
                errs.append(f"{name}: a remote provider needs a non-empty allowed_models list")
            if not str(p.get("base_url") or "").startswith("https://"):
                errs.append(f"{name}: a remote provider needs an https:// base_url")
        if not errs:
            specs[name] = ProviderSpec(
                name=name, base_url=p.get("base_url"), base_url_env=p.get("base_url_env"),
                model_env=p.get("model_env"), key_env=p.get("key_env"), self_hosted=hosted,
                region=p.get("region"), allowed_models=tuple(allowed), extra_body=copy.deepcopy(extra))
    default = doc.get("default")
    if default not in raw:
        errs.append(f"default {default!r} is not a configured provider")
    if errs:
        raise LLMError("providers.yaml: " + "; ".join(errs))
    return default, specs


def load_providers(path: Path = PROVIDERS_FILE) -> tuple[str, dict[str, ProviderSpec]]:
    import yaml
    return parse_providers(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def check_permitted(spec: ProviderSpec, model: str | None, *, need_model: bool = True) -> None:
    """The policy gate. Self-hosted providers always pass. A remote provider needs the explicit fictional-data
    opt-in AND an allowlisted open-weight model. Raises ProviderNotPermitted before any network call."""
    if spec.self_hosted:
        return
    if os.environ.get(ALLOW_REMOTE_ENV) != ALLOW_REMOTE_VALUE:
        raise ProviderNotPermitted(
            f"remote provider {spec.name!r} is not permitted: set {ALLOW_REMOTE_ENV}={ALLOW_REMOTE_VALUE} in the "
            f"process environment (fictional data only; it is not read from .env)")
    if not need_model:
        return
    if not model:
        raise ProviderNotPermitted(f"remote provider {spec.name!r} needs an explicit model from its allowlist")
    if model not in spec.allowed_models:
        raise ProviderNotPermitted(
            f"model {model!r} is not on the open-weight allowlist of provider {spec.name!r} "
            f"(config/providers.yaml)")


# --------------------------------------------------------------------------- metrics

@dataclass
class CallMetrics:
    """Measured numbers of one chat call. Nothing is estimated: unknown values are None."""
    provider: str
    model: str | None
    self_hosted: bool
    ttft_ms: float | None           # request start -> first non-empty content delta; None when not streamed
    wall_ms: float                  # request start -> last byte of the successful attempt
    input_tokens: int | None
    output_tokens: int | None
    tokens_per_s: float | None      # output tokens / wall clock (not the generating window), as honest as it gets
    cost_usd: float | None          # only from usage.cost in the response (OpenRouter), else None
    streamed: bool
    attempts: int                   # 1 = first try worked, 2-3 = fell back to a plain / unconstrained request

    def to_dict(self) -> dict:
        return asdict(self)


def _int_or_none(x) -> int | None:
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def build_metrics(spec: ProviderSpec, model: str | None, usage: dict | None, ttft_s: float | None, wall_s: float,
                  streamed: bool, attempts: int) -> CallMetrics:
    usage = usage if isinstance(usage, dict) else {}
    out_tokens = _int_or_none(usage.get("completion_tokens"))
    cost = usage.get("cost")
    return CallMetrics(
        provider=spec.name, model=model, self_hosted=spec.self_hosted,
        ttft_ms=None if ttft_s is None else round(ttft_s * 1000, 1),
        wall_ms=round(wall_s * 1000, 1),
        input_tokens=_int_or_none(usage.get("prompt_tokens")), output_tokens=out_tokens,
        tokens_per_s=round(out_tokens / wall_s, 2) if out_tokens is not None and wall_s > 0 else None,
        cost_usd=float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
        streamed=streamed, attempts=attempts)


# --------------------------------------------------------------------------- client

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the Authorization header to the new host, and a loopback-only
    client could be bounced to a remote one. A 3xx surfaces as an HTTP error instead."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)

@dataclass
class _Reply:
    text: str
    usage: dict | None
    served_model: str | None
    ttft_s: float | None
    streamed: bool = False          # True only when the reply really arrived as an SSE stream


class OpenAICompatClient:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 300.0, *,
                 spec: ProviderSpec | None = None, now: Callable[[], float] = time.perf_counter):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model = model
        self.model_revision: str | None = None
        if spec is None:
            # No registry entry, so no allowlist or opt-in to check: only a local endpoint is acceptable.
            host = urllib.parse.urlparse(base_url).hostname
            if host not in _LOOPBACK_HOSTS:
                raise ProviderNotPermitted(
                    "a client built without a ProviderSpec may only talk to a loopback URL "
                    "(127.0.0.1 / localhost); use get_client() with a provider from config/providers.yaml")
            spec = ProviderSpec(name="custom", base_url=base_url, self_hosted=True)
        self.spec = spec
        self._now = now
        self.metrics: list[CallMetrics] = []
        self.last_metrics: CallMetrics | None = None

    def __repr__(self) -> str:
        return f"OpenAICompatClient(provider={self.spec.name!r}, model={self.model!r})"

    def effective_extra_body(self) -> dict:
        """The provider options that really go into every request (reserved and, for remote providers, unvetted
        keys are dropped). Part of any cache key whose response depends on them."""
        return {k: copy.deepcopy(v) for k, v in self.spec.extra_body.items()
                if k not in RESERVED_BODY_KEYS and (self.spec.self_hosted or k in REMOTE_EXTRA_BODY_KEYS)}

    def version_info(self) -> dict:
        """Values for schemas.Versions: llm, provider, self_hosted."""
        return {"llm": f"{self.model}@{self.model_revision}", "provider": self.spec.name,
                "self_hosted": self.spec.self_hosted}

    # -- http plumbing

    def _scrub(self, text: str) -> str:
        key = os.environ.get(self.spec.key_env) if self.spec.key_env else None
        return text.replace(key, "***") if key and len(key) >= 4 else text

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.spec.key_env:
            key = os.environ.get(self.spec.key_env)
            if not key:
                raise LLMError(f"{self.spec.key_env} is not set (needed by provider {self.spec.name!r})")
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _open(self, url: str, payload: dict | None, timeout: float):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(),
                                     method="GET" if payload is None else "POST")
        try:
            return _OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = self._scrub(e.read(65536).decode(errors="replace"))[:500]
            raise HTTPStatusError(e.code, f"HTTP {e.code} from {url}: {body}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise _Unreachable(self._scrub(f"cannot reach {url}: {e}")) from None

    def _get_json(self, url: str, timeout: float, payload: dict | None = None) -> dict:
        with self._open(url, payload, timeout) as r:
            try:
                return json.loads(r.read().decode())
            except (OSError, ValueError, http.client.HTTPException) as e:
                raise LLMError(self._scrub(f"bad response from {url}: {e}")) from None

    # -- model discovery

    def probe(self) -> dict:
        """GET /models: confirms the endpoint is up and resolves model id + revision (vLLM `root`)."""
        check_permitted(self.spec, self.model)
        listing = self._get_json(f"{self.base_url}/models", 10)
        models = listing.get("data", [])
        if not models:
            raise LLMError(f"{self.base_url}/models lists no models")
        chosen = next((m for m in models if m.get("id") == self.model), None) if self.model else models[0]
        if chosen is None:
            raise LLMError(f"model {self.model!r} not served; available: {[m.get('id') for m in models][:20]}")
        self.model = chosen["id"]
        self.model_revision = chosen.get("root") or chosen.get("id")
        return chosen

    def list_models(self) -> list[str]:
        """GET /models, ids only. Gated like every call, but needs no model."""
        check_permitted(self.spec, self.model, need_model=False)
        listing = self._get_json(f"{self.base_url}/models", 30)
        return [m["id"] for m in listing.get("data", []) if isinstance(m, dict) and m.get("id")]

    # -- chat

    def chat(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,
             json_schema: dict | None = None, stream: bool = True) -> str:
        return self.chat_with_metrics(messages, temperature, max_tokens, json_schema, stream)[0]

    def chat_with_metrics(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,
                          json_schema: dict | None = None, stream: bool = True) -> tuple[str, CallMetrics]:
        check_permitted(self.spec, self.model)
        # (stream?, constrained?) in order. Streaming gives a real TTFT but must never be a requirement: any
        # failure falls back to a plain request (vLLM is the production path), and a 400 on the json_schema
        # falls back to an unconstrained request (older vLLM), the caller parses defensively.
        steps = [(True, json_schema is not None)] if stream else []
        steps += [(False, json_schema is not None)]
        if json_schema is not None:
            steps += [(False, False)]
        for i, (streamed, constrained) in enumerate(steps):
            payload = {"model": self.model, "messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens}
            if constrained:
                payload["response_format"] = {"type": "json_schema",
                                              "json_schema": {"name": "answer", "schema": json_schema}}
            payload.update(self.effective_extra_body())
            t0 = self._now()
            try:
                reply = self._stream(payload, t0) if streamed else self._plain(payload)
            except LLMError as e:
                last = i == len(steps) - 1
                no_retry = isinstance(e, (_Unreachable, ProviderNotPermitted)) or (
                    isinstance(e, HTTPStatusError) and e.status in (301, 302, 303, 307, 308, 401, 403, 429))
                if last or no_retry or (not streamed and not (isinstance(e, HTTPStatusError) and e.status == 400)):
                    raise
                continue
            wall = self._now() - t0
            if self.model_revision is None and not self.spec.self_hosted:
                self.model_revision = reply.served_model or "unversioned"
            metrics = build_metrics(self.spec, self.model, reply.usage, reply.ttft_s, wall, reply.streamed, i + 1)
            self.metrics.append(metrics)
            self.last_metrics = metrics
            return reply.text, metrics
        raise LLMError("no request was attempted")      # unreachable: steps is never empty

    def _plain(self, payload: dict) -> _Reply:
        url = f"{self.base_url}/chat/completions"
        return self._parse_plain(self._get_json(url, self.timeout, payload))

    def _parse_plain(self, out: dict) -> _Reply:
        try:
            text = out["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LLMError(f"unexpected response shape: {self._scrub(str(out))[:300]}") from None
        return _Reply(text, out.get("usage"), out.get("model"), None)

    def _stream(self, payload: dict, t0: float) -> _Reply:
        url = f"{self.base_url}/chat/completions"
        payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        parts: list[str] = []
        usage = served = None
        ttft: float | None = None
        first = True
        finished = False        # saw [DONE] or a choice with a finish_reason
        with self._open(url, payload, self.timeout) as r:
            try:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if first and not line.startswith("data:"):
                        # the server ignored `stream` and answered with one plain JSON body
                        body = (line + r.read().decode("utf-8", "replace")).strip()
                        try:
                            return self._parse_plain(json.loads(body))
                        except (ValueError, LLMError) as e:
                            raise _StreamFailed(self._scrub(f"unusable reply to a stream request: {e}")) from None
                    first = False
                    if not line.startswith("data:"):
                        raise _StreamFailed("malformed stream line")
                    data = line[5:].strip()
                    if data == "[DONE]":
                        finished = True
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        raise _StreamFailed("malformed stream chunk") from None
                    if not isinstance(chunk, dict):
                        raise _StreamFailed("malformed stream chunk")
                    if chunk.get("error"):
                        raise _StreamFailed(f"error inside stream: {self._scrub(str(chunk['error']))[:300]}")
                    served = chunk.get("model") or served
                    usage = chunk.get("usage") or usage
                    choices = chunk.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices and isinstance(choices[0], dict) else {}
                    if choices and isinstance(choices[0], dict) and choices[0].get("finish_reason"):
                        finished = True
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        if ttft is None:
                            ttft = self._now() - t0
                        parts.append(piece)
            except (OSError, http.client.HTTPException) as e:
                raise _StreamFailed(self._scrub(f"stream cut off: {e}")) from None
        if not finished:
            raise _StreamFailed("stream ended without a terminal event (truncated)")
        if not parts:
            raise _StreamFailed("stream carried no content")
        return _Reply("".join(parts), usage, served, ttft, streamed=True)


def get_client(provider: str | None = None, model: str | None = None, *, providers_file: Path = PROVIDERS_FILE,
               timeout: float = 300.0, now: Callable[[], float] = time.perf_counter,
               need_model: bool = True) -> OpenAICompatClient:
    """Client for a provider from config/providers.yaml. The policy gate runs here, before anything else.

    Provider: argument, else $SENTINEL_LLM_PROVIDER, else `default` in providers.yaml.
    Model: argument, else the provider's `model_env`, else $SENTINEL_LLM_MODEL. A remote provider needs an explicit allowlisted model
    (`need_model=False` only for model discovery, which still needs the remote opt-in).
    """
    load_env()
    default, specs = load_providers(providers_file)
    name = provider or os.environ.get(PROVIDER_ENV) or default
    if name not in specs:
        raise LLMError(f"unknown provider {name!r}; configured: {sorted(specs)}")
    spec = specs[name]
    model = model or (os.environ.get(spec.model_env) if spec.model_env else None) or os.environ.get(MODEL_ENV) or None
    check_permitted(spec, model, need_model=need_model)
    return OpenAICompatClient(spec.resolve_base_url(), model, timeout, spec=spec, now=now)


def from_env() -> OpenAICompatClient:
    """The configured default client (self-hosted vLLM unless $SENTINEL_LLM_PROVIDER says otherwise)."""
    return get_client()


# --------------------------------------------------------------------------- cache

class DiskCache:
    """JSON files keyed by sha256 of the canonical request (content + provider + model + prompt + runtime)."""

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


def extraction_cache_key(segments: list[dict], model_id: str, model_revision: str, prompt_version: str, *,
                         provider: str) -> str:
    """Cache key of one fact-extraction request: transcript content + provider + model id/revision + prompt
    version + runtime. Never a key, URL or header.

    `segments` are {id, speaker, text} dicts. Keyword hits and every config/ file are deliberately NOT inputs, so
    editing keywords.json, rules.yaml or thresholds.json never invalidates cached extractions. Provisional until
    pipeline/extract.py (M4) adopts it.
    """
    return DiskCache.key({
        "step": "extract",
        "segments": [{"id": s["id"], "speaker": s["speaker"], "text": s["text"]} for s in segments],
        "provider": provider, "model_id": model_id, "model_revision": model_revision,
        "prompt_version": prompt_version, "runtime": RUNTIME_VERSION,
    })
