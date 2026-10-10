"""Settings: thresholds (tuning) and keywords + rules (configuration), docs/API.md "Settings".

GET returns the current values, PUT validates and saves them, POST /settings/preview answers
"what would change if I used these values?" without saving (the live impact panel while dragging).

Fixture mode: config/thresholds.json, keywords.json and rules.yaml do not exist yet (config milestone),
so values start from MOCK defaults and PUT keeps them in memory only (lost on restart). Nothing is
re-run, so PUT answers n_calls = 0. The shapes follow the proposals in docs/API.md.
"""
from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from pipeline import schemas

from .deps import ApiError, store

router = APIRouter(prefix="/api/settings")

# Which pipeline steps a change re-runs (CLAUDE.md "Re-run cost").
RERUN_STAGES = {
    "thresholds": ["rules", "confidence", "decide"],
    "keywords": ["keywords", "rules", "confidence", "decide"],
    "rules": ["rules", "confidence", "decide"],
}
# Decision paths that force review whatever the thresholds are (decide.py step 1).
FORCED_REVIEW_PATHS = {"stage_error", "missing_evidence", "contradictory_evidence"}


# --------------------------------------------------------------------------- MOCK defaults
def _default_thresholds() -> dict:
    trace = store.get_doc("call_MOCK_001", "trace")
    return dict(trace["thresholds"]) if trace else {"alarm": 0.7, "review": 0.4, "confidence_gate": 0.5}


DEFAULT_KEYWORDS = {   # same MOCK values as the web app's fixtures mode (web/lib/data.ts)
    "fuzzy_threshold": 0.85,
    "families": {
        "access": {"criterion": "credential_sharing", "terms": ["Passwort", "PIN", "Zugangscode"],
                   "variants": {"Passwort": ["Passwörter", "Passwoort"], "PIN": ["Pin-Code"]}},
        "trade": {"criterion": "insider_trading", "terms": ["Aktie", "Kauforder"],
                  "variants": {"Aktie": ["Aktiä"]}},
        "disclosure": {"criterion": "third_party_disclosure", "terms": ["Kontostand", "Vermögen"], "variants": {}},
        "documentation": {"criterion": "documentation_concealment",
                          "terms": ["nöd notiere", "nicht protokollieren"], "variants": {}},
        "splitting": {"criterion": "control_evasion", "terms": ["aufteile", "Teilbeträge"], "variants": {}},
        "numbers": {"criterion": "payment_card_data", "terms": ["Kartenummer", "IBAN"], "variants": {}},
    },
}
DEFAULT_RULES = {"version": "MOCK",
                 "rules": [{"criterion": c, "enabled": True} for c in schemas.CRITERIA if c != "other"]}

# The current values (in memory in fixture mode).
current: dict[str, Any] = {}


def reset() -> None:
    """Back to the MOCK defaults (also used by the tests)."""
    current.update(thresholds=_default_thresholds(), keywords=copy.deepcopy(DEFAULT_KEYWORDS),
                   rules=copy.deepcopy(DEFAULT_RULES))


reset()


# --------------------------------------------------------------------------- validation
def _is_unit(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1


def validate_thresholds(t: Any) -> list[str]:
    if not isinstance(t, dict):
        return ["thresholds must be an object"]
    keys = {"alarm", "review", "confidence_gate"}
    errs = [f"thresholds: unknown key {k!r}" for k in t if k not in keys]
    errs += [f"thresholds.{k}: required" for k in keys if k not in t]
    errs += [f"thresholds.{k}: must be a number in [0, 1]" for k in keys & t.keys() if not _is_unit(t[k])]
    if not errs and not t["review"] < t["alarm"]:
        errs.append("thresholds: review must be lower than alarm")
    return errs


def validate_keywords(k: Any) -> list[str]:
    if not isinstance(k, dict) or not isinstance(k.get("families"), dict):
        return ["keywords must be an object with a 'families' object"]
    errs = [] if _is_unit(k.get("fuzzy_threshold")) else ["keywords.fuzzy_threshold: must be a number in [0, 1]"]
    for name, fam in k["families"].items():
        where = f"keywords.families.{name}"
        if name not in schemas.CRITERION_BY_FAMILY:
            errs.append(f"{where}: unknown family (allowed: {', '.join(schemas.CRITERION_BY_FAMILY)})")
            continue
        if not isinstance(fam, dict):
            errs.append(f"{where}: must be an object")
            continue
        if fam.get("criterion") != schemas.CRITERION_BY_FAMILY[name]:
            errs.append(f"{where}.criterion: must be {schemas.CRITERION_BY_FAMILY[name]!r}")
        terms = fam.get("terms")
        if not isinstance(terms, list) or not all(isinstance(x, str) and x.strip() for x in terms):
            errs.append(f"{where}.terms: must be a list of non-empty strings")
        variants = fam.get("variants", {})
        if not isinstance(variants, dict) or not all(
                isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v) for v in variants.values()):
            errs.append(f"{where}.variants: must map a term to a list of non-empty strings")
    return errs


def validate_rules(r: Any) -> list[str]:
    if not isinstance(r, dict) or not isinstance(r.get("rules"), list):
        return ["rules must be an object with a 'rules' list"]
    errs = [] if isinstance(r.get("version"), str) else ["rules.version: must be a string"]
    seen = set()
    for i, rule in enumerate(r["rules"]):
        if not isinstance(rule, dict):
            errs.append(f"rules.rules[{i}]: must be an object")
            continue
        c = rule.get("criterion")
        if not isinstance(c, str) or c not in schemas.CRITERIA:
            errs.append(f"rules.rules[{i}].criterion: unknown criterion {c!r}")
        elif c in seen:
            errs.append(f"rules.rules[{i}].criterion: duplicate {c!r}")
        else:
            seen.add(c)   # only valid strings; a list or dict here would crash set.add
        if not isinstance(rule.get("enabled"), bool):
            errs.append(f"rules.rules[{i}].enabled: must be true or false")
    return errs


VALIDATORS = {"thresholds": validate_thresholds, "keywords": validate_keywords, "rules": validate_rules}


def normalize_keywords(k: dict) -> dict:
    """Copy of a valid keywords config where every family has a `variants` object (empty if omitted).
    The web settings screen reads `variants[term]` directly, so the field must always exist."""
    k = copy.deepcopy(k)
    for fam in k["families"].values():
        fam.setdefault("variants", {})
    return k


def _save(kind: str, body: Any) -> JSONResponse:
    errors = VALIDATORS[kind](body)
    if errors:
        raise ApiError(422, "invalid", errors)   # nothing is saved
    current[kind] = normalize_keywords(body) if kind == "keywords" else copy.deepcopy(body)
    # Fixture mode: nothing is re-run, so no call changes.
    return JSONResponse(status_code=202, content={"rerun": {"stages": RERUN_STAGES[kind], "n_calls": 0}})


# --------------------------------------------------------------------------- GET / PUT
@router.get("/thresholds")
def get_thresholds() -> dict:
    return current["thresholds"]


@router.put("/thresholds")
def put_thresholds(body: Any = Body(...)) -> JSONResponse:
    return _save("thresholds", body)


@router.get("/keywords")
def get_keywords() -> dict:
    return current["keywords"]


@router.put("/keywords")
def put_keywords(body: Any = Body(...)) -> JSONResponse:
    return _save("keywords", body)


@router.get("/rules")
def get_rules() -> dict:
    return current["rules"]


@router.put("/rules")
def put_rules(body: Any = Body(...)) -> JSONResponse:
    return _save("rules", body)


# --------------------------------------------------------------------------- preview
def _decide(row: dict, trace: dict | None, th: dict) -> str | None:
    """Re-apply the decide.py priority order to a cached call with other thresholds.
    MOCK approximation: uses the row's risk and confidence; the real version re-runs rules + confidence."""
    if row.get("decision") is None or row.get("risk_score") is None:
        return None   # not finished yet
    forced = row.get("n_stage_errors", 0) > 0 or (trace and trace.get("decision_path") in FORCED_REVIEW_PATHS)
    if forced or row.get("confidence") is None or row["confidence"] < th["confidence_gate"]:
        return "review"
    if row["risk_score"] >= th["alarm"]:
        return "alarm"
    if row["risk_score"] >= th["review"]:
        return "review"
    return "no_alert"


@router.post("/preview")
def preview(body: Any = Body(...)) -> dict:
    """Does not save. Fast: only cached data (no ASR, no LLM)."""
    if not isinstance(body, dict):
        raise ApiError(422, "invalid", "body must be an object with any of: thresholds, keywords, rules")
    errors = [f"unknown key {k!r}" for k in body if k not in VALIDATORS]
    errors += [e for kind, v in body.items() if kind in VALIDATORS for e in VALIDATORS[kind](v)]
    if errors:
        raise ApiError(422, "invalid", errors)

    th_before = current["thresholds"]
    th_after = body.get("thresholds", th_before)
    keywords = normalize_keywords(body["keywords"]) if "keywords" in body else current["keywords"]
    rules = body.get("rules", current["rules"])

    rows = store.list_calls()
    traces = {r["call_id"]: store.get_doc(r["call_id"], "trace") for r in rows}
    transcripts = {r["call_id"]: store.get_doc(r["call_id"], "transcript") for r in rows}

    counts = {"before": {d: 0 for d in schemas.DECISIONS}, "after": {d: 0 for d in schemas.DECISIONS}}
    changed = []
    for row in rows:
        before = _decide(row, traces[row["call_id"]], th_before)
        after = _decide(row, traces[row["call_id"]], th_after)
        if before:
            counts["before"][before] += 1
        if after:
            counts["after"][after] += 1
        if before and after and before != after:
            changed.append({"call_id": row["call_id"], "decision_before": before, "decision_after": after,
                            "risk_before": row["risk_score"], "risk_after": row["risk_score"]})

    # Keyword hits: case-insensitive substring count per segment (MOCK; real fuzzy matching is keywords.py).
    segments = [s["text"].lower() for t in transcripts.values() if t for s in t["segments"]]
    keyword_hit_counts = {
        family: {term: sum(term.lower() in s for s in segments)
                 for term in fam["terms"] + [v for vs in fam.get("variants", {}).values() for v in vs]}
        for family, fam in keywords["families"].items()
    }

    enabled = {r["criterion"] for r in rules["rules"] if r["enabled"]}
    rule_fire_counts = {c: 0 for c in sorted(enabled)}
    for trace in traces.values():
        for rule in (trace or {}).get("rules", []):
            if rule["criterion"] in enabled and rule["risk"] >= th_after["review"]:
                rule_fire_counts[rule["criterion"]] += 1

    return {"decision_counts": counts, "changed": changed,
            "keyword_hit_counts": keyword_hit_counts, "rule_fire_counts": rule_fire_counts}
