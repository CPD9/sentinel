"""Language routing per speaker -> ~/Developer/sentinel-runs/dialect/<call_id>.json (display only, optional step).

    python scripts/dialect_map.py --langid-dir <dir> [--research <dialect_research.json>] [--out DIR] [--call-id X]

Input: the per-call language-ID files from scripts/pod_langid.py (Whisper language detection over each speaker's
turns, averaged by speech seconds). Output: a `DialectEstimate` (pipeline/schemas.py) per call: per speaker
(advisor / customer) `language_probs` (de / fr / it / en / other) and `region_probs` over the language regions in
config/dialect_regions.json, plus method, model, confidence and what it was validated on.

Optional research block (--research): the SwissDial dialect classifier's top 3 per speaker, written only if its
cross-validation was measured and its CI lower bound beats chance. Not part of ./run.sh, never read by the pipeline,
never used in a decision. Probabilities over regions, never a location.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import DIALECT_LANGUAGES, DialectEstimate  # noqa: E402

REGIONS = json.loads((REPO_ROOT / "config" / "dialect_regions.json").read_text(encoding="utf-8"))
DEFAULT_OUT = Path.home() / "Developer" / "sentinel-runs" / "dialect"
METHOD = ("Whisper language detection (faster-whisper large-v3-turbo) on each speaker's turns in <=30 s windows, "
          "probabilities averaged by speech seconds; regions = canton-level majority language")
MIN_SPEECH_S = {"high": 60.0, "medium": 15.0}


def normalise(p: dict[str, float]) -> dict[str, float]:
    """Clip negatives, rescale to sum 1, round to 4 places, fix the rounding residue on the largest entry."""
    q = {k: max(0.0, float(v)) for k, v in p.items()}
    s = sum(q.values())
    if s <= 0:
        raise ValueError("probabilities sum to 0")
    q = {k: round(v / s, 4) for k, v in q.items()}
    top = max(q, key=q.get)
    q[top] = round(q[top] + 1.0 - sum(q.values()), 4)
    return q


def collapse_languages(whisper_probs: dict[str, float]) -> dict[str, float]:
    """Whisper's ~100-language distribution -> de / fr / it / en / other."""
    out = {k: 0.0 for k in DIALECT_LANGUAGES}
    for lang, p in whisper_probs.items():
        out[lang if lang in out else "other"] += p
    return normalise(out)


def language_to_regions(lang: dict[str, float]) -> dict[str, float]:
    """de -> de_ch, fr -> fr_ch, it -> it_ch; English and anything else -> 'other' (not on the map)."""
    out = {r: lang.get(v["language"], 0.0) for r, v in REGIONS["language_regions"].items()}
    out["other"] = sum(p for k, p in lang.items() if k not in {v["language"] for v in REGIONS["language_regions"].values()})
    return normalise(out)


def confidence(speech_s: float, top_p: float) -> str:
    if speech_s >= MIN_SPEECH_S["high"] and top_p >= 0.9:
        return "high"
    if speech_s >= MIN_SPEECH_S["medium"] and top_p >= 0.6:
        return "medium"
    return "low"


def build(langid: dict, validated_on: list[str], research: dict | None = None) -> dict:
    speakers = []
    for role in ("advisor", "customer"):
        s = (langid.get("speakers") or {}).get(role)
        if not s or not s.get("probs"):
            continue
        lp = collapse_languages(s["probs"])
        sp = {"role": role, "speech_s": round(float(s["speech_s"]), 1), "chunks": int(s["chunks"]),
              "language_probs": lp, "region_probs": language_to_regions(lp),
              "confidence": confidence(float(s["speech_s"]), max(lp.values())), "research_dialect": None}
        r = (research or {}).get("calls", {}).get(langid["call_id"], {}).get(role)
        if research and r and research["cv_ci95"][0] > research["chance"]:
            sp["research_dialect"] = {"top3": r["top3"], "cv_accuracy": research["cv_accuracy"],
                                      "cv_ci95": research["cv_ci95"], "chance": research["chance"],
                                      "warning": research["warning"]}
        speakers.append(sp)
    d = {"call_id": langid["call_id"], "method": METHOD, "model": langid["model"], "validated_on": validated_on,
         "speakers": speakers}
    DialectEstimate.from_dict(d)                      # raises SchemaError on anything malformed
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--langid-dir", type=Path, required=True)
    ap.add_argument("--validation", type=Path, default=REPO_ROOT / "artifacts" / "metrics" / "langid_validation.json")
    ap.add_argument("--research", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--call-id")
    a = ap.parse_args(argv)
    val = json.loads(a.validation.read_text(encoding="utf-8")) if a.validation.is_file() else {}
    validated_on = val.get("summary_lines", [])
    research = json.loads(a.research.read_text(encoding="utf-8")) if a.research else None
    files = sorted(a.langid_dir.glob(f"{a.call_id or 'call_*'}.json"))
    for f in files:
        d = build(json.loads(f.read_text(encoding="utf-8")), validated_on, research)
        write_json_atomic(a.out / f"{d['call_id']}.json", d)
    print(f"wrote {len(files)} files to {a.out}")
    return 0 if files else 1


if __name__ == "__main__":
    sys.exit(main())
