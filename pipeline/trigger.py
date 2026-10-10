"""Step 11: report each alarm to the Outcept trigger API.

Contract (case repo README): POST {base}/triggers, JSON {url (absolute http/https, required), title (<= 200),
description (<= 2000, optional)}; 201 returns the stored trigger; no auth. `url` should link straight to the
suspicious passage; our deep link is `<UI base>/calls/<call_id>?t=<seconds>` (the case README only gives
`?t=<seconds>` as an example, so this is our convention).

DRY-RUN BY DEFAULT: payloads are written to out/triggers/<call_id>_<n>.json and nothing is sent. A real POST
happens only if TRIGGER_URL is set (the trigger API base, e.g. http://localhost:8080). The UI base for deep
links is SENTINEL_UI_BASE_URL (default http://127.0.0.1:3000). Alarms only. A trigger failure is a StageError
and never changes the decision.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.io import write_json_atomic
from pipeline.schemas import Finding, StageError

TITLE_MAX, DESCRIPTION_MAX = 200, 2000
DEFAULT_UI_BASE = "http://127.0.0.1:3000"


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def build_payloads(call_id: str, decision: str, findings: list[Finding], ui_base: str | None = None) -> list[dict]:
    base = (ui_base or os.environ.get("SENTINEL_UI_BASE_URL") or DEFAULT_UI_BASE).rstrip("/")
    out = []
    for f in findings:
        ev = next((e for e in f.evidence if e.start_s is not None), f.evidence[0] if f.evidence else None)
        url = f"{base}/calls/{call_id}"
        if ev is not None and ev.start_s is not None:
            url += f"?t={int(ev.start_s)}"
        quote = f' Quote: "{ev.text}"' if ev is not None else ""
        out.append({"url": url,
                    "title": _clip(f"{decision}: {f.criterion} in {call_id}", TITLE_MAX),
                    "description": _clip(f"{f.reason} (risk {f.risk:.2f}).{quote}", DESCRIPTION_MAX)})
    return out


def _post(base: str, payload: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(base.rstrip("/") + "/triggers", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return {"status": r.status, "body": json.loads(r.read().decode() or "{}")}


def send_triggers(call_id: str, decision: str, findings: list[Finding], out_dir: Path,
                  ui_base: str | None = None) -> tuple[list[dict], list[StageError]]:
    """Only for alarms. Returns (records, errors); each record holds the payload and what happened to it."""
    if decision != "alarm":
        return [], []
    target = os.environ.get("TRIGGER_URL")
    records, errors = [], []
    for n, payload in enumerate(build_payloads(call_id, decision, [f for f in findings if f.risk > 0], ui_base)):
        rec: dict = {"mode": "send" if target else "dry-run", "payload": payload}
        if target:
            try:
                rec["response"] = _post(target, payload)
            except urllib.error.HTTPError as e:
                rec["error"] = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"
            if "error" in rec:
                errors.append(StageError("trigger", f"{call_id} trigger {n}: {rec['error']}"))
        try:
            write_json_atomic(Path(out_dir) / f"{call_id}_{n}.json", rec)
        except Exception as e:
            errors.append(StageError("trigger", f"{call_id}: cannot write payload file: {e}"))
        records.append(rec)
    return records, errors
