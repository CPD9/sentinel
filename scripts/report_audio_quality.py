"""Does the audio-quality score separate clean from noisy dev calls?  (Report script: may read the variant label.)

AUC (positive = clean; predictor = call_score, and raw call_snr_db for comparison) with a 95 % bootstrap CI that
resamples whole dialogue groups (clean + noisy takes of one dialogue stay together).

    python scripts/report_audio_quality.py [--split dev] [--resamples 2000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.audio_analysis import OUT_DIR  # noqa: E402

INFERENCE = REPO_ROOT / "artifacts" / "manifests" / "inference.json"
SPLITS = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
METRICS = REPO_ROOT / "artifacts" / "metrics" / "audio_quality_separation.json"


def auc(score: np.ndarray, pos: np.ndarray) -> float:
    """P(score_pos > score_neg) + 0.5 P(tie), exact over all pairs."""
    p, n = score[pos], score[~pos]
    if len(p) == 0 or len(n) == 0:
        return float("nan")
    d = p[:, None] - n[None, :]
    return float(((d > 0).sum() + 0.5 * (d == 0).sum()) / d.size)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "holdout", "test"])
    ap.add_argument("--allow-test", action="store_true", help="final run only: the test split is locked")
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    if a.split == "test" and not a.allow_test:
        raise SystemExit("the test split is locked; pass --allow-test only for the final run")

    variant = {c["call_id"]: c["variant"] for c in json.loads(INFERENCE.read_text())["calls"]}
    groups = json.loads(SPLITS.read_text())["splits"][a.split]["groups"]
    rows = []   # (group index, call_id, clean?, score, snr)
    for gi, g in enumerate(groups):
        for cid in g["call_ids"]:
            f = OUT_DIR / cid / "analysis.json"
            if not f.exists() or variant[cid] not in ("clean", "noisy"):
                continue
            q = json.loads(f.read_text())["audio_quality"]
            if q is None:
                continue
            rows.append((gi, cid, variant[cid] == "clean", q["call_score"], q["call_snr_db"]))
    if not rows:
        raise SystemExit("no analysis artifacts found; run python -m pipeline.audio_analysis first")
    gid = np.array([r[0] for r in rows]); clean = np.array([r[2] for r in rows])
    out: dict = {"split": a.split, "n_calls": len(rows), "n_clean": int(clean.sum()), "n_noisy": int((~clean).sum()),
                 "n_groups": len(set(gid.tolist())), "resamples": a.resamples, "seed": a.seed}
    rng = np.random.default_rng(a.seed)
    ug = np.unique(gid)
    for name, idx in (("call_score", 3), ("call_snr_db", 4)):
        x = np.array([r[idx] for r in rows], dtype=float)
        point = auc(x, clean)
        vals, skipped = [], 0
        for _ in range(a.resamples):
            pick = rng.choice(ug, size=len(ug), replace=True)
            sel = np.concatenate([np.where(gid == g)[0] for g in pick])
            v = auc(x[sel], clean[sel])
            if np.isnan(v):
                skipped += 1
            else:
                vals.append(v)
        lo, hi = np.percentile(vals, [2.5, 97.5])
        out[name] = {"auc": round(point, 4), "ci95": [round(float(lo), 4), round(float(hi), 4)], "skipped_resamples": skipped,
                     "median_clean": round(float(np.median(x[clean])), 3), "median_noisy": round(float(np.median(x[~clean])), 3),
                     "min_clean": round(float(x[clean].min()), 3), "max_noisy": round(float(x[~clean].max()), 3)}
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
