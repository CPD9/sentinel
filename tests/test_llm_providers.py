"""Provider registry, policy gate, secrecy and metrics of pipeline/llm.py. No network: urlopen is faked."""
from __future__ import annotations

import io
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pipeline import llm
from pipeline.llm import (LLMError, ProviderNotPermitted, ProviderSpec, check_permitted, extraction_cache_key,
                          get_client, load_providers, parse_providers)

KEY = "sk-test-SECRET123"
OK_MODEL = "qwen/qwen-2.5-72b-instruct"


class FakeResp:
    def __init__(self, body: bytes):
        self._lines = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        line = self._lines.readline()
        if not line:
            raise StopIteration
        return line

    def read(self):
        return self._lines.read()


class FlakyStream(FakeResp):
    """Delivers some lines, then the connection resets."""
    def __next__(self):
        line = self._lines.readline()
        if not line:
            raise ConnectionResetError("reset by peer")
        return line


def sse(*chunks) -> FakeResp:
    return FakeResp(b"".join(b"data: " + (c if isinstance(c, bytes) else json.dumps(c).encode()) + b"\n\n"
                             for c in chunks))


def delta(text: str, **extra) -> dict:
    return {"model": "served/model-1", "choices": [{"delta": {"content": text}}], **extra}


def plain(text="hallo", usage=None) -> FakeResp:
    out = {"model": "served/model-1", "choices": [{"message": {"content": text}}]}
    if usage is not None:
        out["usage"] = usage
    return FakeResp(json.dumps(out).encode())


def http_error(code: int, body: str = "nope") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x/y", code, "err", {}, io.BytesIO(body.encode()))


class Net:
    """Fake urlopen: pops one scripted response (or exception) per call and records the requests."""
    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data) if req.data else None
        self.calls.append({"url": req.full_url, "headers": dict(req.header_items()), "body": body})
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(llm, "load_env", lambda *a, **k: None)      # never touch the real .env
    for v in (llm.ALLOW_REMOTE_ENV, llm.PROVIDER_ENV, "LLM_MODEL", "LLM_BASE_URL", "OPENROUTER_API_KEY",
              "INFOMANIAK_API_TOKEN", "INFOMANIAK_PRODUCT_ID"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")


def net(monkeypatch, *script) -> Net:
    n = Net(*script)
    monkeypatch.setattr(llm._OPENER, "open", n)
    return n


def allow(monkeypatch):
    monkeypatch.setenv(llm.ALLOW_REMOTE_ENV, llm.ALLOW_REMOTE_VALUE)


MSG = [{"role": "user", "content": "hi"}]


# --------------------------------------------------------------------------- the gate

@pytest.mark.parametrize("value", [None, "1", "true", "fictional_data_only ", "FICTIONAL_DATA_ONLY"])
def test_remote_blocked_without_exact_env(monkeypatch, value):
    n = net(monkeypatch)
    if value is not None:
        monkeypatch.setenv(llm.ALLOW_REMOTE_ENV, value)
    with pytest.raises(ProviderNotPermitted):
        get_client("openrouter", OK_MODEL)
    assert n.calls == []


@pytest.mark.parametrize("model", ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "mistralai/mistral-large",
                                   "QWEN/QWEN-2.5-72B-INSTRUCT", None, ""])
def test_closed_or_missing_model_blocked_even_with_env(monkeypatch, model):
    n = net(monkeypatch)
    allow(monkeypatch)
    with pytest.raises(ProviderNotPermitted):
        get_client("openrouter", model)
    assert n.calls == []


def test_direct_client_construction_is_gated_too(monkeypatch):
    n = net(monkeypatch)
    spec = load_providers()[1]["openrouter"]
    c = llm.OpenAICompatClient(spec.base_url, "openai/gpt-4o", spec=spec)
    for call in (lambda: c.chat(MSG), c.probe, c.list_models):
        with pytest.raises(ProviderNotPermitted):
            call()
    assert n.calls == []


def test_allowlisted_remote_passes_and_sends_policy_body(monkeypatch):
    allow(monkeypatch)
    n = net(monkeypatch, sse(delta("ha"), delta("llo"), b"[DONE]"))
    c = get_client("openrouter", OK_MODEL)
    assert c.chat(MSG) == "hallo"
    body = n.calls[0]["body"]
    assert body["provider"] == {"data_collection": "deny"} and body["usage"] == {"include": True}
    assert body["model"] == OK_MODEL and body["stream"] is True
    assert n.calls[0]["headers"]["Authorization"] == f"Bearer {KEY}"        # sent, but see the secrecy tests
    assert n.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert c.model_revision == "served/model-1"


def test_list_models_needs_env_but_no_model(monkeypatch):
    n = net(monkeypatch)
    with pytest.raises(ProviderNotPermitted):
        get_client("openrouter", None, need_model=False)         # discovery still needs the opt-in
    allow(monkeypatch)
    with pytest.raises(ProviderNotPermitted):
        get_client("openrouter", None)                           # a chat client needs a model
    assert get_client("openrouter", None, need_model=False).model is None
    spec = load_providers()[1]["openrouter"]
    c = llm.OpenAICompatClient(spec.base_url, None, spec=spec)
    n.script.append(FakeResp(json.dumps({"data": [{"id": OK_MODEL}, {"id": "openai/gpt-4o"}]}).encode()))
    assert c.list_models() == [OK_MODEL, "openai/gpt-4o"]


def test_self_hosted_needs_no_env(monkeypatch):
    n = net(monkeypatch, plain("ok"))
    c = get_client()                                    # default = apertus_aws
    assert c.spec.name == "apertus_aws" and c.spec.self_hosted
    assert c.chat(MSG, stream=False) == "ok"
    assert n.calls[0]["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert "Authorization" not in n.calls[0]["headers"]
    get_client("ollama_local", "llama3")                # no network needed to construct


def test_provider_env_selects_provider(monkeypatch):
    monkeypatch.setenv(llm.PROVIDER_ENV, "ollama_local")
    assert get_client().spec.name == "ollama_local"
    with pytest.raises(LLMError, match="unknown provider"):
        get_client("nope")


def test_remote_opt_in_is_never_taken_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.undo()                                  # use the real load_env on a temp file
    monkeypatch.delenv(llm.ALLOW_REMOTE_ENV, raising=False)
    monkeypatch.delenv("SOME_OTHER_VAR", raising=False)
    f = tmp_path / ".env"
    f.write_text(f"{llm.ALLOW_REMOTE_ENV}={llm.ALLOW_REMOTE_VALUE}\nSOME_OTHER_VAR=1\n")
    try:
        llm.load_env(f)
        import os
        assert llm.ALLOW_REMOTE_ENV not in os.environ and os.environ["SOME_OTHER_VAR"] == "1"
    finally:
        import os
        os.environ.pop("SOME_OTHER_VAR", None)


# --------------------------------------------------------------------------- secrecy

def test_key_never_leaks(monkeypatch, caplog):
    allow(monkeypatch)
    caplog.set_level(logging.DEBUG)
    spec = load_providers()[1]["openrouter"]
    c = get_client("openrouter", OK_MODEL)
    surfaces = [repr(c), str(c), repr(spec), repr(c.__dict__)]
    # an upstream error body that echoes the key must be scrubbed from the raised error
    net(monkeypatch, http_error(400, f"bad request, token {KEY} rejected"),
        http_error(400, f"bad request, token {KEY} rejected"), http_error(500, f"boom {KEY}"))
    with pytest.raises(LLMError) as ei:
        c.chat(MSG, json_schema={"type": "object"})
    surfaces += [str(ei.value), repr(ei.value)]
    # unreachable
    net(monkeypatch, urllib.error.URLError(f"tls failed for {KEY}"))
    with pytest.raises(LLMError) as ei:
        c.chat(MSG)
    surfaces += [str(ei.value)]
    # a successful call: metrics and the cache key
    net(monkeypatch, sse(delta("x"), {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1,
                                                                   "cost": 0.0001}}, b"[DONE]"))
    c.chat(MSG)
    surfaces += [json.dumps([m.to_dict() for m in c.metrics]), json.dumps(c.version_info())]
    surfaces.append(extraction_cache_key([{"id": "s1", "speaker": "advisor", "text": "t"}], OK_MODEL, "r", "p1",
                                         provider="openrouter"))
    surfaces.append(caplog.text)
    for s in surfaces:
        assert KEY not in s


def test_missing_key_error_names_only_the_variable(monkeypatch):
    allow(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    net(monkeypatch)
    c = get_client("openrouter", OK_MODEL)
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY is not set"):
        c.chat(MSG)


# --------------------------------------------------------------------------- metrics

class Clock:
    def __init__(self, *ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0)


def test_stream_metrics_with_cost(monkeypatch):
    allow(monkeypatch)
    # now() calls: t0, first content delta, end of attempt
    clock = Clock(10.0, 10.25, 12.0)
    net(monkeypatch, sse(delta(""), delta("Ein"), delta(" Passwort"),
                         {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 7, "cost": 0.00042}},
                         b"[DONE]"))
    c = get_client("openrouter", OK_MODEL, now=clock)
    text, m = c.chat_with_metrics(MSG)
    assert text == "Ein Passwort"
    assert (m.ttft_ms, m.wall_ms) == (250.0, 2000.0)
    assert (m.input_tokens, m.output_tokens) == (12, 7)
    assert m.tokens_per_s == 3.5                        # 7 tokens / 2.0 s wall clock
    assert m.cost_usd == 0.00042 and m.streamed and m.attempts == 1
    assert (m.provider, m.model, m.self_hosted) == ("openrouter", OK_MODEL, False)
    assert c.last_metrics is m and c.metrics == [m]


def test_no_usage_means_none_not_a_guess(monkeypatch):
    net(monkeypatch, plain("ok"))
    c = get_client(now=Clock(0.0, 1.0))
    _, m = c.chat_with_metrics(MSG, stream=False)
    assert (m.input_tokens, m.output_tokens, m.tokens_per_s, m.cost_usd, m.ttft_ms) == (None,) * 5
    assert m.wall_ms == 1000.0 and not m.streamed


def test_plain_metrics_with_usage_but_no_cost(monkeypatch):
    net(monkeypatch, plain("ok", {"prompt_tokens": 5, "completion_tokens": 20}))
    c = get_client(now=Clock(0.0, 0.5))
    _, m = c.chat_with_metrics(MSG, stream=False)
    assert m.tokens_per_s == 40.0 and m.cost_usd is None


# --------------------------------------------------------------------------- non-streaming fallback (vLLM path)

def test_fallback_when_server_rejects_stream(monkeypatch):
    n = net(monkeypatch, http_error(400, "stream_options not supported"), plain("ok", {"completion_tokens": 2}))
    c = get_client()
    text, m = c.chat_with_metrics(MSG)
    assert text == "ok" and not m.streamed and m.attempts == 2 and m.ttft_ms is None
    assert n.calls[0]["body"]["stream"] is True and "stream" not in n.calls[1]["body"]


def test_fallback_on_garbled_stream(monkeypatch):
    net(monkeypatch, FakeResp(b"data: {not json\n\n"), plain("recovered"))
    assert get_client().chat(MSG) == "recovered"


def test_fallback_on_empty_stream_and_on_reset(monkeypatch):
    net(monkeypatch, sse(b"[DONE]"), plain("one"))
    assert get_client().chat(MSG) == "one"
    net(monkeypatch, FlakyStream(b'data: {"choices":[{"delta":{"content":"par"}}]}\n\n'), plain("two"))
    assert get_client().chat(MSG) == "two"          # partial text is discarded


def test_plain_json_answer_to_a_stream_request_is_accepted(monkeypatch):
    n = net(monkeypatch, FakeResp(json.dumps({"choices": [{"message": {"content": "pretty"}}]}, indent=2).encode()))
    text, m = get_client().chat_with_metrics(MSG)
    assert text == "pretty" and m.ttft_ms is None and len(n.calls) == 1
    assert m.streamed is False                      # it arrived as one body, whatever was requested


def test_json_schema_400_retries_unconstrained(monkeypatch):
    n = net(monkeypatch, http_error(400, "no schema"), http_error(400, "no schema"), plain("{}"))
    assert get_client().chat(MSG, json_schema={"type": "object"}) == "{}"
    assert "response_format" in n.calls[0]["body"] and "response_format" in n.calls[1]["body"]
    assert "response_format" not in n.calls[2]["body"]


def test_no_fallback_for_unreachable_or_auth(monkeypatch):
    n = net(monkeypatch, urllib.error.URLError("refused"))
    with pytest.raises(LLMError, match="cannot reach"):
        get_client().chat(MSG)
    assert len(n.calls) == 1
    n = net(monkeypatch, http_error(401, "bad key"))
    with pytest.raises(LLMError, match="HTTP 401"):
        get_client().chat(MSG)
    assert len(n.calls) == 1


def test_both_attempts_failing_raises(monkeypatch):
    net(monkeypatch, http_error(500), http_error(500))
    with pytest.raises(LLMError, match="HTTP 500"):
        get_client().chat(MSG)


# --------------------------------------------------------------------------- registry file and cache key

def test_providers_yaml_contract():
    default, specs = load_providers()
    assert default == "apertus_aws"
    assert specs["apertus_aws"].self_hosted and specs["apertus_aws"].base_url_env == "LLM_BASE_URL"
    assert specs["ollama_local"].base_url == "http://127.0.0.1:11434/v1"
    for name in ("infomaniak", "openrouter"):
        s = specs[name]
        assert not s.self_hosted and s.allowed_models and s.base_url.startswith("https://") and s.key_env
    assert specs["infomaniak"].region == "CH"
    assert specs["openrouter"].extra_body["provider"] == {"data_collection": "deny"}
    text = (Path(llm.PROVIDERS_FILE)).read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]|Bearer |api[_-]?key\s*:\s*\S", text)       # env names only


def test_infomaniak_url_placeholder(monkeypatch):
    s = load_providers()[1]["infomaniak"]
    with pytest.raises(LLMError, match="INFOMANIAK_PRODUCT_ID"):
        s.resolve_base_url()
    monkeypatch.setenv("INFOMANIAK_PRODUCT_ID", "123")
    assert s.resolve_base_url() == "https://api.infomaniak.com/2/ai/123/openai/v1"


@pytest.mark.parametrize("patch", [
    {"key_env": "sk-abc123"},                                   # a value, not an env name
    {"allowed_models": []},
    {"base_url": "http://openrouter.ai/api/v1"},
    {"self_hosted": "no"},
    {"surprise": 1},
])
def test_registry_validation_rejects_bad_specs(patch):
    p = {"base_url": "https://r.example/v1", "key_env": "R_KEY", "self_hosted": False, "allowed_models": ["a/b"]}
    with pytest.raises(LLMError):
        parse_providers({"default": "r", "providers": {"r": {**p, **patch}}})


def test_cache_key_includes_provider_model_revision():
    segs = [{"id": "s1", "speaker": "advisor", "text": "Grüezi"}]
    base = extraction_cache_key(segs, "m", "r1", "p1", provider="apertus_aws")
    assert base == extraction_cache_key(segs, "m", "r1", "p1", provider="apertus_aws")
    assert base != extraction_cache_key(segs, "m", "r1", "p1", provider="openrouter")
    assert base != extraction_cache_key(segs, "m2", "r1", "p1", provider="apertus_aws")
    assert base != extraction_cache_key(segs, "m", "r2", "p1", provider="apertus_aws")
    assert base != extraction_cache_key(segs, "m", "r1", "p2", provider="apertus_aws")


def test_check_permitted_message_has_no_key():
    spec = ProviderSpec(name="r", base_url="https://r/v1", key_env="R_KEY", self_hosted=False, allowed_models=("a/b",))
    with pytest.raises(ProviderNotPermitted) as e:
        check_permitted(spec, "a/b")
    assert "R_KEY" not in str(e.value)


# --------------------------------------------------------------------------- Codex review of PR #16

@pytest.mark.parametrize("url", ["https://evil.example/v1", "http://10.0.0.5:8000/v1", "http://127.0.0.1.evil.io/v1",
                                 "not a url"])
def test_direct_client_without_spec_must_be_loopback(monkeypatch, url):
    n = net(monkeypatch)
    with pytest.raises(ProviderNotPermitted):
        llm.OpenAICompatClient(url, "m")
    assert n.calls == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/v1", "http://localhost:11434/v1", "http://[::1]:8000/v1"])
def test_direct_client_without_spec_loopback_is_fine(monkeypatch, url):
    net(monkeypatch, plain("ok"))
    assert llm.OpenAICompatClient(url, "m").chat(MSG, stream=False) == "ok"


def test_extra_body_cannot_set_reserved_fields(monkeypatch):
    doc = {"default": "r", "providers": {"r": {
        "base_url": "https://r.example/v1", "key_env": "OPENROUTER_API_KEY", "self_hosted": False,
        "allowed_models": [OK_MODEL], "extra_body": {"model": "openai/gpt-4o"}}}}
    with pytest.raises(LLMError, match="reserved"):
        parse_providers(doc)
    # defence in depth: a spec built by hand still cannot override the gated model or the schema
    allow(monkeypatch)
    spec = ProviderSpec(name="r", base_url="https://r.example/v1", key_env="OPENROUTER_API_KEY", self_hosted=False,
                        allowed_models=(OK_MODEL,),
                        extra_body={"model": "openai/gpt-4o", "response_format": {"type": "text"},
                                    "provider": {"data_collection": "deny"}})
    n = net(monkeypatch, plain("ok"))
    llm.OpenAICompatClient(spec.base_url, OK_MODEL, spec=spec).chat(MSG, stream=False)
    assert n.calls[0]["body"]["model"] == OK_MODEL
    assert "response_format" not in n.calls[0]["body"]
    assert n.calls[0]["body"]["provider"] == {"data_collection": "deny"}


def test_stream_that_ends_without_terminal_event_falls_back(monkeypatch):
    n = net(monkeypatch, sse(delta("par"), delta("tial")), plain("complete answer"))
    text, m = get_client().chat_with_metrics(MSG)
    assert text == "complete answer" and not m.streamed and m.attempts == 2 and len(n.calls) == 2


def test_finish_reason_counts_as_terminal_event(monkeypatch):
    done = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    net(monkeypatch, sse(delta("all"), done))
    text, m = get_client().chat_with_metrics(MSG)
    assert text == "all" and m.streamed and m.attempts == 1


def test_malformed_plain_response_is_scrubbed(monkeypatch):
    allow(monkeypatch)
    body = json.dumps({"error": {"message": f"invalid token {KEY}"}}).encode()
    net(monkeypatch, FakeResp(body))
    with pytest.raises(LLMError) as ei:
        get_client("openrouter", OK_MODEL).chat(MSG, stream=False)
    assert KEY not in str(ei.value) and "unexpected response shape" in str(ei.value)


# --------------------------------------------------------------------------- Codex review round 2 of PR #16

def _doc(host_remote: bool, extra: dict) -> dict:
    p = {"base_url": "https://r.example/v1" if host_remote else "http://127.0.0.1:8000/v1",
         "self_hosted": not host_remote, "extra_body": extra}
    if host_remote:
        p.update(key_env="OPENROUTER_API_KEY", allowed_models=[OK_MODEL])
    return {"default": "r", "providers": {"r": p}}


@pytest.mark.parametrize("key", ["models", "route", "preset"])
def test_model_fallback_fields_are_reserved(monkeypatch, key):
    for remote in (True, False):
        with pytest.raises(LLMError, match="reserved"):
            parse_providers(_doc(remote, {key: ["openai/gpt-4o"]}))
    # and ignored at request time even for a hand-built spec
    allow(monkeypatch)
    spec = ProviderSpec(name="r", base_url="https://r.example/v1", key_env="OPENROUTER_API_KEY", self_hosted=False,
                        allowed_models=(OK_MODEL,), extra_body={key: ["openai/gpt-4o"]})
    n = net(monkeypatch, plain("ok"))
    llm.OpenAICompatClient(spec.base_url, OK_MODEL, spec=spec).chat(MSG, stream=False)
    assert key not in n.calls[0]["body"]


def test_remote_extra_body_is_allowlisted_but_self_hosted_may_pass_vendor_options():
    with pytest.raises(LLMError, match="not allowed for a remote provider"):
        parse_providers(_doc(True, {"top_k": 5}))
    _, specs = parse_providers(_doc(True, {"provider": {"data_collection": "deny"}, "usage": {"include": True}}))
    assert set(specs["r"].extra_body) == {"provider", "usage"}
    _, specs = parse_providers(_doc(False, {"chat_template_kwargs": {"enable_thinking": False}}))
    assert "chat_template_kwargs" in specs["r"].extra_body                 # vLLM options stay possible


def test_redirects_are_never_followed(monkeypatch):
    h = llm._NoRedirect()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=b"{}",
                                 headers={"Authorization": f"Bearer {KEY}"})
    for code in (301, 302, 303, 307, 308):
        assert h.redirect_request(req, None, code, "Found", {}, "https://evil.example/steal") is None
    assert llm._OPENER.handlers and any(isinstance(x, llm._NoRedirect) for x in llm._OPENER.handlers)
    allow(monkeypatch)
    n = net(monkeypatch, http_error(302, "moved"))
    with pytest.raises(LLMError, match="HTTP 302") as ei:
        get_client("openrouter", OK_MODEL).chat(MSG)
    assert len(n.calls) == 1 and KEY not in str(ei.value)                   # no retry, nothing forwarded


def test_key_straddling_the_truncation_boundary_is_still_scrubbed(monkeypatch):
    allow(monkeypatch)
    c = get_client("openrouter", OK_MODEL)
    # malformed 200 (plain), key placed so that a truncate-then-scrub would cut it in half
    pad = "x" * (300 - 8)
    net(monkeypatch, FakeResp(json.dumps({"error": pad + KEY}).encode()))
    with pytest.raises(LLMError) as e1:
        c.chat(MSG, stream=False)
    # HTTP error body, same trick at the 500 boundary
    net(monkeypatch, http_error(500, "y" * (500 - 8) + KEY))
    with pytest.raises(LLMError) as e2:
        c.chat(MSG, stream=False)
    # error object inside a stream (call the stream step directly, chat() would swallow it into the fallback)
    net(monkeypatch, sse({"error": {"message": "z" * (300 - 30) + KEY}}))
    with pytest.raises(llm._StreamFailed) as e3:
        c._stream({"model": OK_MODEL, "messages": MSG}, 0.0)
    for e in (e1, e2, e3):
        assert KEY[:8] not in str(e.value), str(e.value)


# --------------------------------------------------------------------------- Codex review round 3 of PR #16

def test_remote_provider_selected_by_env_needs_model_env_not_a_cli_flag(monkeypatch):
    allow(monkeypatch)
    monkeypatch.setenv(llm.PROVIDER_ENV, "openrouter")
    with pytest.raises(ProviderNotPermitted, match="explicit model"):
        llm.from_env()                                       # provider chosen, model missing
    monkeypatch.setenv(llm.MODEL_ENV, OK_MODEL)
    c = llm.from_env()
    assert (c.spec.name, c.model) == ("openrouter", OK_MODEL)
    monkeypatch.setenv(llm.MODEL_ENV, "openai/gpt-4o")      # the gate still applies to the env-selected model
    with pytest.raises(ProviderNotPermitted):
        llm.from_env()


def test_default_provider_model_env_beats_sentinel_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "swiss-ai/Apertus-v1.5-8B")
    monkeypatch.setenv(llm.MODEL_ENV, "something-else")
    assert get_client().model == "swiss-ai/Apertus-v1.5-8B"


def test_effective_extra_body_reflects_what_is_really_sent():
    remote = ProviderSpec(name="r", base_url="https://r/v1", key_env="K", self_hosted=False, allowed_models=("a/b",),
                          extra_body={"provider": {"data_collection": "deny"}, "top_k": 5, "model": "x"})
    local = ProviderSpec(name="l", base_url="http://127.0.0.1:1/v1", self_hosted=True,
                         extra_body={"chat_template_kwargs": {"enable_thinking": False}, "model": "x"})
    assert llm.OpenAICompatClient("https://r/v1", "a/b", spec=remote).effective_extra_body() == \
        {"provider": {"data_collection": "deny"}}
    assert llm.OpenAICompatClient("http://127.0.0.1:1/v1", "m", spec=local).effective_extra_body() == \
        {"chat_template_kwargs": {"enable_thinking": False}}


# --------------------------------------------------------------------------- Codex review round 5 of PR #16

@pytest.mark.parametrize("url", ["https://evil.example/api/v1", "http://openrouter.ai/api/v1",
                                 "https://openrouter.ai.evil.example/api/v1", "https://openrouter.ai:8443/api/v1"])
def test_spec_credentials_cannot_be_sent_to_another_origin(monkeypatch, url):
    allow(monkeypatch)
    n = net(monkeypatch)
    spec = load_providers()[1]["openrouter"]
    with pytest.raises(ProviderNotPermitted, match="does not match"):
        llm.OpenAICompatClient(url, OK_MODEL, spec=spec)
    assert n.calls == []


def test_matching_origin_is_accepted_whatever_the_path_or_case(monkeypatch):
    spec = load_providers()[1]["openrouter"]
    for url in ("https://openrouter.ai/api/v1", "https://OpenRouter.ai/other/path/", "https://openrouter.ai:443/x"):
        assert llm.OpenAICompatClient(url, OK_MODEL, spec=spec).spec is spec
    monkeypatch.setenv("INFOMANIAK_PRODUCT_ID", "42")
    inf = load_providers()[1]["infomaniak"]
    assert llm.OpenAICompatClient(inf.resolve_base_url(), "llama3", spec=inf)
    with pytest.raises(ProviderNotPermitted):
        llm.OpenAICompatClient("https://api.infomaniak.com.evil.io/2/ai/42/openai/v1", "llama3", spec=inf)
