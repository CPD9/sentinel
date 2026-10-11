"""Figures for docs/RESULTS.md and the README -> docs/assets/results/*.png + *.svg.

    python scripts/make_figures.py --judge-run ~/Developer/sentinel-runs/s4t_0551_final \
        --rules-run ~/Developer/sentinel-runs/asr_fix_0452

  ladder.*          AUC vs gold escalation with the dialogue-group bootstrap CI, per decision method (chance = 0.5)
  roc.*             ROC curves, facts -> rules vs the direct judge, all 62 calls, ASR mode
  threshold_curve.* false alarms, missed cases and review load over the review threshold (judge risk)
  asr_wer.*         word and character error rate of the final ASR transcripts vs the reference scripts, per split
                    and clean / noisy (Whisper writes Swiss German speech mostly in Standard German, so WER is high)
Inputs are run folders and artifacts/metrics/*.json; labels are read only through pipeline.evaluate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from pipeline import asr_metrics, evaluate  # noqa: E402
from pipeline.reference import reference_transcript  # noqa: E402

OUT = REPO_ROOT / "docs" / "assets" / "results"
METRICS = REPO_ROOT / "artifacts" / "metrics"
INK, MUTED, GRID = "#1f2933", "#7b8794", "#e4e7eb"
JUDGE, RULES, KW, WARN = "#1f6feb", "#c2410c", "#6b7280", "#b42318"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK,
                     "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "figure.dpi": 160})


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote docs/assets/results/{name}.png/.svg")


def judge_scores(run: Path) -> dict[str, float]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))["risk"] for p in sorted((run / "judge").glob("call_0*.json"))}


def rules_scores(run: Path) -> dict[str, float]:
    out = {}
    for p in sorted((run / "traces").glob("call_0*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        out[p.stem] = max((r["risk"] for r in t["rules"]), default=0.0)
    return out


def roc(scores: dict[str, float]) -> list[tuple[float, float]]:
    pts = [(0.0, 0.0)]
    for t in sorted(set(scores.values()), reverse=True):
        e = evaluate.score_decisions({c: "review" if s >= t else "no_alert" for c, s in scores.items()})["all"]["escalation"]
        pts.append((e["fp"] / max(1, e["fp"] + e["tn"]), e["tp"] / max(1, e["tp"] + e["fn"])))
    pts.append((1.0, 1.0))
    return pts


def fig_ladder(judge: dict, rules: dict, prefix: dict | None) -> None:
    rows = []
    if prefix:
        rows.append(("facts → rules, pre-fix (T5)", evaluate.escalation_auc(prefix), RULES))
    rows += [("facts → rules (ASR fix)", evaluate.escalation_auc(rules), RULES),
             ("keywords only", None, KW), ("direct judge S4 (shipped)", evaluate.escalation_auc(judge), JUDGE)]
    je = json.loads((METRICS / "judge_eval.json").read_text(encoding="utf-8"))["scorers"] if (METRICS / "judge_eval.json").is_file() else {}
    kw = je.get("keywords only (hit segments)", {}).get("auc")
    rows = [(n, a if a is not None else kw, c) for n, a, c in rows if (a if a is not None else kw)]
    mc = METRICS / "multi_check_eval.json"
    if mc.is_file():
        r = json.loads(mc.read_text(encoding="utf-8"))["rows"][1]
        rows.append(("multi-check judge (not shipped)" if not json.loads(mc.read_text())["gate_pass"] else
                     "multi-check judge", {"auc": r["auc"], "ci95": r["auc_ci95"]}, "#7c3aed"))
    fig, ax = plt.subplots(figsize=(7.2, 0.62 * len(rows) + 1.2))
    for i, (name, a, col) in enumerate(rows):
        lo, hi = a["ci95"]
        ax.plot([lo, hi], [i, i], color=col, lw=2.2, solid_capstyle="round")
        ax.plot(a["auc"], i, "o", color=col, ms=8)
        ax.text(hi + 0.015, i, f"{a['auc']:.2f}  [{lo:.2f}, {hi:.2f}]", va="center", color=INK, fontsize=9)
    ax.axvline(0.5, color=WARN, ls="--", lw=1)
    ax.text(0.5, len(rows) - 0.45, " chance", color=WARN, fontsize=9)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.set_xlim(0.15, 1.0)
    ax.set_ylim(-0.6, len(rows) - 0.3)
    ax.invert_yaxis()
    ax.set_xlabel("AUC vs gold escalation (95% CI, bootstrap over dialogue groups), all 62 calls, ASR mode")
    ax.grid(axis="y", visible=False)
    save(fig, "ladder")


def fig_roc(judge: dict, rules: dict) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    for name, sc, col in (("direct judge (S4)", judge, JUDGE), ("facts → rules", rules, RULES)):
        a = evaluate.escalation_auc(sc)
        xs, ys = zip(*roc(sc))
        ax.plot(xs, ys, color=col, lw=2, drawstyle="steps-post",
                label=f"{name}: AUC {a['auc']:.2f} [{a['ci95'][0]:.2f}, {a['ci95'][1]:.2f}]")
    ax.plot([0, 1], [0, 1], color=WARN, ls="--", lw=1, label="chance")
    ax.set_xlabel("false positive rate (harmless calls flagged)")
    ax.set_ylabel("true positive rate (escalations found)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    save(fig, "roc")


def fig_threshold() -> None:
    d = json.loads((METRICS / "threshold_curve.json").read_text(encoding="utf-8"))
    pts = d["review_threshold"]
    x = [p["review"] for p in pts]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.plot(x, [p["missed"] for p in pts], color=RULES, lw=2, label="missed cases (of 34)")
    ax.plot(x, [p["false_alarms"] for p in pts], color=WARN, lw=2, label="false alarms")
    ax.set_xlabel("review threshold on the judge's risk (alarm threshold 0.70)")
    ax.set_ylabel("calls")
    ax2 = ax.twinx()
    ax2.plot(x, [100 * p["review_load"] for p in pts], color=JUDGE, lw=2, ls="-.", label="review load (% of calls)")
    ax2.set_ylabel("review load, % of calls", color=JUDGE)
    ax2.set_ylim(0, 105)
    ax2.grid(False)
    cur = d["current"]["review"]
    ax.axvline(cur, color=MUTED, ls=":", lw=1)
    ax.text(cur + 0.01, ax.get_ylim()[1] * 0.92, f"default {cur:.2f}", color=MUTED, fontsize=9)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="center right", fontsize=8, frameon=False)
    save(fig, "threshold_curve")


def fig_wer(judge_run: Path) -> None:
    inf = {c["call_id"]: c for c in json.loads((REPO_ROOT / "artifacts" / "manifests" / "inference.json").read_text())["calls"]}
    splits = json.loads((REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json").read_text())["splits"]
    rows: dict[tuple, list] = {}
    for s, d in splits.items():
        for c in d["call_ids"]:
            p = judge_run / "transcripts" / f"{c}.json"
            if not p.is_file():
                continue
            hyp = " ".join(x["text"] for x in json.loads(p.read_text(encoding="utf-8"))["segments"])
            ref = " ".join(t["text"] for t in reference_transcript(c))
            rows.setdefault((s, inf[c]["variant"]), []).append((asr_metrics.wer(ref, hyp), asr_metrics.cer(ref, hyp)))
    keys = sorted(rows)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    w = 0.38
    for i, k in enumerate(keys):
        wv = sum(r[0] for r in rows[k]) / len(rows[k])
        cv = sum(r[1] for r in rows[k]) / len(rows[k])
        ax.bar(i - w / 2, wv, w, color=JUDGE, label="WER" if i == 0 else None)
        ax.bar(i + w / 2, cv, w, color=KW, label="CER" if i == 0 else None)
        ax.text(i - w / 2, wv + 0.01, f"{wv:.2f}", ha="center", fontsize=8)
        ax.text(i + w / 2, cv + 0.01, f"{cv:.2f}", ha="center", fontsize=8)
    ax.set_xticks(range(len(keys)), [f"{s}\n{v} (n={len(rows[(s, v)])})" for s, v in keys], fontsize=8)
    ax.set_ylabel("error rate vs reference script")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("faster-whisper large-v3-turbo (GPU), final transcripts; reference = Swiss German scripts",
                 fontsize=9, color=MUTED)
    save(fig, "asr_wer")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge-run", type=Path, required=True)
    ap.add_argument("--rules-run", type=Path, required=True)
    ap.add_argument("--prefix-pred", type=Path, default=REPO_ROOT / "artifacts" / "predictions" / "pipeline_asr_final.json")
    a = ap.parse_args(argv)
    judge, rules = judge_scores(a.judge_run), rules_scores(a.rules_run)
    prefix = None
    if a.prefix_pred.is_file():
        prefix = {c["call_id"]: c["risk_score"] for c in json.loads(a.prefix_pred.read_text(encoding="utf-8"))["calls"]}
    fig_ladder(judge, rules, prefix)
    fig_roc(judge, rules)
    fig_threshold()
    fig_wer(a.judge_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
