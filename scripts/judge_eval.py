"""Direct judge (S4) on ASR transcripts vs the baselines, all 62 calls, with 3-fold CV over dev / Testset_30 / holdout.

    python scripts/judge_eval.py [--run] [--workers 8] [--facts-traces DIR]

--run   judges every call (cached in artifacts/cache/judge) and writes artifacts/judge/<call_id>.json
Then, for each scorer (S4 judge risk, facts->rules risk, keywords-only, flag-all, flag-none):
  AUC vs gold escalation (dialogue-group bootstrap CI), and an escalation threshold chosen by 3-fold CV:
  tuned on two splits by balanced accuracy, scored on the third; out-of-fold balanced accuracy and escalation
  P / R / F1 are the headline. Labels stay inside pipeline.evaluate. Writes artifacts/metrics/judge_eval.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from pipeline import decide as dec  # noqa: E402
from pipeline import evaluate, judge  # noqa: E402
from pipeline import keywords as kw  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import Transcript  # noqa: E402

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
TRANSCRIPTS = REPO_ROOT / "artifacts" / "transcripts"
JUDGE_DIR = REPO_ROOT / "artifacts" / "judge"
SPLITS = ("dev", "test", "holdout")


def transcript(cid: str) -> Transcript:
    return Transcript.from_dict(json.loads((TRANSCRIPTS / f"{cid}.json").read_text(encoding="utf-8")))


def run_judge(ids: list[str], workers: int) -> None:
    from pipeline import llm
    client = llm.get_client()
    client.probe()

    def one(cid):
        r = judge.judge_call(transcript(cid), client=client)
        write_json_atomic(JUDGE_DIR / f"{cid}.json", r.to_dict())
        print(f"{cid}: {r.decision:8s} risk {r.risk:.2f} {r.criterion:24s} citations {len(r.valid_citations)}/"
              f"{len(r.citations)} valid{' (cached)' if r.cached else ''}", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, ids))


def bacc(flags: dict[str, bool]) -> tuple[float, dict]:
    m = evaluate.score_decisions({c: "review" if f else "no_alert" for c, f in flags.items()})["all"]
    e = m["escalation"]
    return (e["tp"] / max(1, e["tp"] + e["fn"]) + e["tn"] / max(1, e["tn"] + e["fp"])) / 2, e


def cv(scores: dict[str, float], ids: dict[str, list[str]]) -> dict:
    cands = sorted(set(scores.values())) + [float("inf")]
    folds, oof = {}, {}
    for held in SPLITS:
        train = [c for s in SPLITS if s != held for c in ids[s]]
        t = max(cands, key=lambda t: (bacc({c: scores[c] >= t for c in train})[0], t))    # ties: fewer flags
        b, e = bacc({c: scores[c] >= t for c in ids[held]})
        folds[held] = {"threshold": t, "bacc": round(b, 4), "esc_p": e["precision"], "esc_r": e["recall"], "esc_f1": e["f1"]}
        oof.update({c: scores[c] >= t for c in ids[held]})
    b, e = bacc(oof)
    vals = [folds[s]["bacc"] for s in SPLITS]
    return {"folds": folds, "cv_bacc_mean": round(sum(vals) / 3, 4), "cv_bacc_range": [min(vals), max(vals)],
            "oof_bacc": round(b, 4), "oof_esc_p": e["precision"], "oof_esc_r": e["recall"], "oof_esc_f1": e["f1"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--facts-traces", type=Path, default=REPO_ROOT / "artifacts" / "traces")
    a = ap.parse_args(argv)
    sp = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"]
    ids = {s: sp[s]["call_ids"] for s in SPLITS}
    allc = [c for s in SPLITS for c in ids[s]]
    if a.run:
        run_judge(allc, a.workers)
    jd = {c: json.loads((JUDGE_DIR / f"{c}.json").read_text(encoding="utf-8")) for c in allc}
    cfg = dec.load_config()
    kwseg = {}
    for c in allc:
        fam: dict[str, set] = {}
        for h in kw.find_hits(transcript(c), cfg.keywords):
            fam.setdefault(h.family, set()).add(h.segment_id)
        kwseg[c] = float(max((len(v) for v in fam.values()), default=0))
    scorers = {
        "S4 direct judge (risk)": {c: jd[c]["risk"] for c in allc},
        "facts -> rules (risk)": {c: json.loads((a.facts_traces / f"{c}.json").read_text(encoding="utf-8"))["risk_score"]
                                  for c in allc},
        "keywords only (hit segments)": kwseg,
        "flag-all": {c: 1.0 for c in allc},
        "flag-none": {c: 0.0 for c in allc},
    }
    out = {}
    for name, sc in scorers.items():
        out[name] = {"auc": evaluate.escalation_auc(sc), "cv": cv(sc, ids)}
        au, c = out[name]["auc"], out[name]["cv"]
        f = lambda x: "n/a" if x is None else f"{x:.2f}"
        print(f"{name:30s} AUC {f(au['auc'])} [{f(au['ci95'][0])}, {f(au['ci95'][1])}] by split "
              f"{ {k: f(v) for k, v in au['by_split'].items()} } | CV bacc {c['cv_bacc_mean']:.2f} "
              f"({c['cv_bacc_range'][0]:.2f}-{c['cv_bacc_range'][1]:.2f}) | OOF esc P {f(c['oof_esc_p'])} R "
              f"{f(c['oof_esc_r'])} F1 {f(c['oof_esc_f1'])}")
    vc = sum(len([x for x in jd[c]["citations"] if x["valid"]]) for c in allc)
    nc = sum(len(jd[c]["citations"]) for c in allc)
    flagged = [c for c in allc if jd[c]["decision"] != "no_alert"]
    print(f"judge citations: {vc}/{nc} valid; flagged calls without a valid citation: "
          f"{[c for c in flagged if not any(x['valid'] for x in jd[c]['citations'])]}")
    write_json_atomic(REPO_ROOT / "artifacts" / "metrics" / "judge_eval.json",
                      {"scorers": out, "citations_valid": vc, "citations_total": nc,
                       "judge_version": judge.PROMPT_VERSION_FULL})
    # crossval.json "methods": per method AUC with its CI and CV precision / recall / balanced accuracy per fold
    cvp = REPO_ROOT / "artifacts" / "metrics" / "crossval.json"
    doc = json.loads(cvp.read_text(encoding="utf-8")) if cvp.is_file() else {}
    doc["methods"] = {name: {"auc": o["auc"]["auc"], "auc_ci95": o["auc"]["ci95"], "auc_by_split": o["auc"]["by_split"],
                             "cv_bacc_mean": o["cv"]["cv_bacc_mean"], "cv_bacc_range": o["cv"]["cv_bacc_range"],
                             "cv_folds": o["cv"]["folds"], "oof_esc_p": o["cv"]["oof_esc_p"],
                             "oof_esc_r": o["cv"]["oof_esc_r"], "oof_esc_f1": o["cv"]["oof_esc_f1"]}
                      for name, o in out.items()}
    doc["methods_note"] = ("all 62 calls, ASR mode; AUC vs gold escalation with a dialogue-group bootstrap CI; CV = "
                           "escalation threshold tuned on two splits by balanced accuracy, scored on the third")
    write_json_atomic(cvp, doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
