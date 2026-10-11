"""SwissDial dialect classifier (research only): measured with held-out sentences, shown only if above chance.

    python scripts/dialect_research.py clips <clips.json>                       # SwissDial clip list for pod_langid
    python scripts/dialect_research.py cv <swissdial.json from pod_langid clips --embed> <calls_dir with _embeddings.npz>

Features: mean-pooled Whisper large-v3-turbo encoder output (1280-d) per clip / per speaker window.
Classifier: standardised logistic regression over the 8 SwissDial dialects (ag be bs gr lu sg vs zh).
Evaluation: 5-fold cross-validation grouped by sentence (the same sentence is never in train and test), accuracy
with a 95 % bootstrap CI over sentences, against 1/8 chance.

The confound, stated wherever this is shown: SwissDial has ONE speaker per dialect, so "dialect" and "voice" are the
same label here; a classifier can reach high accuracy by recognising the speaker. It cannot be validated speaker-
independently with this data, and the case calls it is applied to are synthetic (TTS) voices. Output is therefore
`low confidence` research, kept out of the map and out of every decision.

Writes artifacts/metrics/dialect_swissdial.json (CV result) and, only if the CI lower bound beats chance,
~/Developer/sentinel-runs/dialect_research.json (per call and speaker top 3; consumed by scripts/dialect_map.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "swissdial.json"
METRICS = REPO_ROOT / "artifacts" / "metrics" / "dialect_swissdial.json"
RESEARCH_OUT = Path.home() / "Developer" / "sentinel-runs" / "dialect_research.json"
WARNING = ("Research only, low confidence. Trained on 8 speakers, one per dialect (SwissDial), so it reflects the "
           "voice more than the dialect. The case voices are synthetic (TTS). Not on the map, not used in any decision.")


def cmd_clips(a) -> int:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = Path(a.audio_root) if a.audio_root else REPO_ROOT
    clips = [{"id": u["utt_id"], "path": str(root / u["audio_path"]), "lang": "de", "dialect": u["dialect"],
              "group": u["sentence_id"], "set": "swissdial"} for u in m["utterances"]]
    Path(a.out).write_text(json.dumps(clips, indent=1), encoding="utf-8")
    print(f"wrote {a.out}: {len(clips)} clips")
    return 0


def cv(X: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = 20261011) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    pred = np.empty_like(y)
    for tr, te in GroupKFold(n_splits=5).split(X, y, groups):
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
        clf.fit(X[tr], y[tr])
        pred[te] = clf.predict(X[te])
    correct = pred == y
    rng = np.random.default_rng(seed)
    ug = np.unique(groups)
    boot = []
    for _ in range(2000):
        g = rng.choice(ug, size=len(ug), replace=True)
        idx = np.concatenate([np.flatnonzero(groups == x) for x in g])
        boot.append(correct[idx].mean())
    labels = sorted(set(y))
    cm = {t: {p: int(((y == t) & (pred == p)).sum()) for p in labels} for t in labels}
    return {"accuracy": round(float(correct.mean()), 4),
            "ci95": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
            "n": int(len(y)), "classes": labels, "chance": round(1 / len(labels), 4), "confusion": cm}


def cmd_cv(a) -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    clips = json.loads(Path(a.clips_result).read_text(encoding="utf-8"))["clips"]
    npz = np.load(Path(a.clips_result).with_suffix(".npz"))
    by_id = {c["id"]: c for c in clips}
    X = npz["emb"]
    y = np.array([by_id[i]["dialect"] for i in npz["id"]])
    g = np.array([by_id[i]["group"] for i in npz["id"]])
    res = cv(X, y, g)
    shown = res["ci95"][0] > res["chance"]
    body = {"created_at": datetime.now(timezone.utc).isoformat(), "data": "SwissDial 1.1, 8 dialects x 20 parallel "
            "sentences, one speaker per dialect", "features": "Whisper large-v3-turbo encoder, mean-pooled (1280-d)",
            "classifier": "StandardScaler + LogisticRegression(C=1)", "evaluation": "5-fold GroupKFold by sentence; "
            "95% CI = bootstrap over sentences (2000)", **res, "shown_in_ui": shown,
            "confound": "one speaker per dialect: dialect and voice are the same label, so this cannot be validated "
                        "speaker-independently; the case voices are synthetic (TTS)"}
    METRICS.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print(f"CV accuracy {res['accuracy']} CI {res['ci95']} chance {res['chance']} -> shown_in_ui={shown}; wrote {METRICS}")
    if not shown:
        RESEARCH_OUT.unlink(missing_ok=True)
        return 0
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0)).fit(X, y)
    ce = np.load(Path(a.calls_dir) / "_embeddings.npz")
    probs = clf.predict_proba(ce["emb"])
    acc: dict[tuple[str, str], list[np.ndarray]] = {}
    for cid, role, p in zip(ce["call_id"], ce["role"], probs):
        acc.setdefault((str(cid), str(role)), []).append(p)
    calls: dict[str, dict] = {}
    for (cid, role), ps in acc.items():
        mean = np.mean(ps, axis=0)
        top = np.argsort(-mean)[:3]
        calls.setdefault(cid, {})[role] = {"top3": [{"region": str(clf.classes_[i]), "p": round(float(mean[i]), 4)}
                                                    for i in top]}
    tops = Counter(r["top3"][0]["region"] for c in calls.values() for r in c.values())
    region, k = tops.most_common(1)[0]
    n = sum(tops.values())
    warning = WARNING
    if k / n >= 0.5:      # the case voices collapse onto one SwissDial speaker: say so where the number is shown
        label = json.loads((REPO_ROOT / "config" / "dialect_regions.json").read_text(encoding="utf-8"))[
            "dialect_regions"].get(region, {}).get("label", region)
        warning += (f" On the case calls, {k} of {n} speakers come out as {label}: the synthetic voices resemble that "
                    f"one SwissDial speaker; this is not a dialect finding.")
    RESEARCH_OUT.write_text(json.dumps({"cv_accuracy": res["accuracy"], "cv_ci95": res["ci95"],
                                        "chance": res["chance"], "warning": warning, "case_top1": dict(tops),
                                        "calls": calls}, indent=1),
                            encoding="utf-8")
    print(f"wrote {RESEARCH_OUT} for {len(calls)} calls")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clips")
    c.add_argument("out")
    c.add_argument("--audio-root", help="where data/swissdial lives on the machine that runs pod_langid")
    v = sub.add_parser("cv")
    v.add_argument("clips_result")
    v.add_argument("calls_dir")
    a = ap.parse_args(argv)
    return cmd_clips(a) if a.cmd == "clips" else cmd_cv(a)


if __name__ == "__main__":
    sys.exit(main())
