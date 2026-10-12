"""Language-ID validation summary -> artifacts/metrics/langid_validation.json (read by scripts/dialect_map.py).

    python scripts/langid_validation.py --clips <swissdial_langid.json> [<fleurs_langid.json> ...] --calls <langid/calls>

For every clip set (output of scripts/pod_langid.py clips): accuracy of Whisper's top language against the gold
language, per gold language, with a 95 % Wilson interval and the confusions. For the case calls: how many speaker
estimates have German on top (all case calls are Swiss German, so anything else is an error). `summary_lines` are the
short "validated on" lines the map shows next to the estimate. Only measured numbers; a set that was not run is absent.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "artifacts" / "metrics" / "langid_validation.json"
NAMES = {"de": "German", "fr": "French", "it": "Italian", "en": "English"}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def clip_set(path: Path) -> dict:
    rows = json.loads(path.read_text(encoding="utf-8"))["clips"]
    by = defaultdict(list)
    for r in rows:
        by[(r.get("set") or path.stem, r["lang"])].append(r)
    out = {}
    for (name, lang), rs in sorted(by.items()):
        k = sum(r["pred"] == lang for r in rs)
        out.setdefault(name, {})[lang] = {
            "n": len(rs), "correct": k, "accuracy": round(k / len(rs), 4), "ci95": wilson(k, len(rs)),
            "predicted": dict(Counter(r["pred"] for r in rs).most_common()),
            "mean_p_gold": round(sum(r["p_gold"] for r in rs) / len(rs), 4),
            "mean_duration_s": round(sum(r["duration_s"] for r in rs) / len(rs), 2)}
    return out


def calls(d: Path) -> dict:
    tops, n_spk = Counter(), 0
    for f in sorted(d.glob("call_*.json")):
        for s in json.loads(f.read_text(encoding="utf-8"))["speakers"].values():
            n_spk += 1
            tops[max(s["probs"], key=s["probs"].get)] += 1
    return {"speakers": n_spk, "top_language": dict(tops.most_common()), "de_on_top": tops["de"],
            "de_share": round(tops["de"] / n_spk, 4) if n_spk else None, "ci95": wilson(tops["de"], n_spk)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", type=Path, nargs="*", default=[])
    ap.add_argument("--calls", type=Path)
    a = ap.parse_args(argv)
    sets: dict = {}
    for p in a.clips:
        for name, v in clip_set(p).items():
            sets.setdefault(name, {}).update(v)
    body = {"created_at": datetime.now(timezone.utc).isoformat(), "method": "Whisper large-v3-turbo detect_language "
            "on <=30 s windows (one clip = one window); top language vs gold", "sets": sets}
    lines = []
    for name, langs in sets.items():
        part = ", ".join(f"{NAMES.get(l, l)} {v['correct']}/{v['n']}" for l, v in langs.items())
        lines.append(f"{name}: {part} correct")
    if a.calls:
        c = calls(a.calls)
        body["case_calls"] = c
        lines.append(f"case calls (Swiss German): German on top for {c['de_on_top']}/{c['speakers']} speakers")
    body["summary_lines"] = lines
    OUT.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
