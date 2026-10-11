"""Multi-check judge vs the single judge, all 62 calls, ASR mode (zero-shot: nothing fitted on labels).

    python scripts/mc_eval.py --run-dir ~/Developer/sentinel-runs/s4t_0551_final [--workers 4]

Runs pipeline.judge_multi on the run's transcripts (cached in artifacts/cache/judge), writes <run-dir>/judge_multi/,
and compares with the run's single-judge answers (<run-dir>/judge/) at the default thresholds of
config/thresholds.json (alarm: risk >= alarm AND a validated citation; review: risk >= review; else no_alert).
Reports AUC with a dialogue-group bootstrap CI, balanced accuracy, escalation P/R, false alarms, review load.
Ship gate (set before measuring): balanced accuracy above the single judge AND false alarms <= 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import evaluate, judge_multi, llm  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import Transcript  # noqa: E402

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"


def decide(j: dict, th: dict) -> str:
    cited = any(c.get("valid") for c in j.get("citations") or [])
    return "alarm" if j["risk"] >= th["alarm"] and cited else "review" if j["risk"] >= th["review"] else "no_alert"


def summary(name: str, judged: dict[str, dict], th: dict) -> dict:
    dec = {c: decide(j, th) for c, j in judged.items()}
    m = evaluate.score_decisions(dec)["all"]
    e = m["escalation"]
    rec, spec = e["tp"] / max(1, e["tp"] + e["fn"]), e["tn"] / max(1, e["tn"] + e["fp"])
    auc = evaluate.escalation_auc({c: j["risk"] for c, j in judged.items()})
    per_split = {}
    for s, sd in json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"].items():
        sub = {c: dec[c] for c in sd["call_ids"] if c in dec}
        es = evaluate.score_decisions(sub)["all"]["escalation"]
        per_split[s] = round((es["tp"] / max(1, es["tp"] + es["fn"]) + es["tn"] / max(1, es["tn"] + es["fp"])) / 2, 4)
    return {"method": name, "auc": auc["auc"], "auc_ci95": auc["ci95"], "auc_by_split": auc["by_split"],
            "bacc": round((rec + spec) / 2, 4), "bacc_by_split": per_split, "esc_p": e["precision"], "esc_r": round(rec, 4),
            "false_alarms": m["three_class"]["confusion"]["no_alert"]["alarm"],
            "review_load": round(sum(d != "no_alert" for d in dec.values()) / len(dec), 4),
            "pred_counts": m["pred_counts"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    ids = sorted(p.stem for p in (a.run_dir / "results").glob("call_0*.json"))
    client = llm.get_client()
    client.probe()

    def one(cid):
        t = Transcript.from_dict(json.loads((a.run_dir / "transcripts" / f"{cid}.json").read_text(encoding="utf-8")))
        r = judge_multi.judge_call_multi(t, client=client)
        d = {**r.to_dict(), "version": judge_multi.PROMPT_VERSION_FULL,
             "checks": [{"criterion": c.criterion, "decision": c.decision, "risk": c.risk,
                         "valid_citations": len(c.valid_citations)} for c in r.checks],
             "failed_checks": r.failed_checks}
        write_json_atomic(a.run_dir / "judge_multi" / f"{cid}.json", d)
        print(f"{cid}: {r.decision:8s} {r.risk:.2f} {r.criterion}", flush=True)
        return cid, d
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        multi = dict(pool.map(one, ids))
    single = {c: json.loads((a.run_dir / "judge" / f"{c}.json").read_text(encoding="utf-8")) for c in ids}
    th = json.loads((REPO_ROOT / "config" / "thresholds.json").read_text(encoding="utf-8"))
    rows = [summary("single judge (S4)", single, th), summary("multi-check judge", multi, th)]
    gate = rows[1]["bacc"] > rows[0]["bacc"] and rows[1]["false_alarms"] <= 1
    nfail = sum(len(d["failed_checks"]) for d in multi.values())
    print(f"failed checks (unusable answer -> review at risk 0.5): {nfail} of {len(multi) * len(judge_multi.CHECKED)}")
    for r in rows:
        print(f"{r['method']:20s} AUC {r['auc']:.2f} [{r['auc_ci95'][0]:.2f}, {r['auc_ci95'][1]:.2f}] | bacc {r['bacc']:.2f} "
              f"{r['bacc_by_split']} | esc P {r['esc_p']} R {r['esc_r']:.2f} | FA {r['false_alarms']} | load "
              f"{r['review_load']:.0%} | {r['pred_counts']}")
    print(f"ship gate (bacc > single AND false alarms <= 1): {'PASS' if gate else 'FAIL'}")
    write_json_atomic(REPO_ROOT / "artifacts" / "metrics" / "multi_check_eval.json",
                      {"rows": rows, "gate_pass": gate, "thresholds": {k: th[k] for k in ("alarm", "review")},
                       "version": judge_multi.PROMPT_VERSION_FULL})
    return 0


if __name__ == "__main__":
    sys.exit(main())
