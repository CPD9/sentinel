"""Per-Stufe breakdown of an ASR benchmark run. Reads labels, so it runs only AFTER the hypotheses exist.

scripts/benchmark_asr.py is label-free and writes artifacts/metrics/asr_benchmark_<ts>.json. This script
joins that file with artifacts/manifests/evaluation.json (Stufe only) and re-aggregates the stored
per-call error counts. It never decodes and never changes the winner.

    python scripts/report_asr_benchmark.py artifacts/metrics/asr_benchmark_<ts>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from benchmark_asr import summarise  # noqa: E402

EVAL_MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "evaluation.json"


def breakdown(bench: dict, evaluation: dict) -> dict:
    out = {}
    for name, m in bench["models"].items():
        rows = m.get("calls") or []
        cells = {}
        for r in rows:
            stufe = evaluation["calls"][r["call_id"]]["stufe"]
            cells.setdefault(f"Stufe{stufe}", []).append(r)
            cells.setdefault(f"Stufe{stufe}/{r['variant']}", []).append(r)
        out[name] = {k: summarise(v) for k, v in sorted(cells.items())}
    return out


def markdown(table: dict) -> str:
    keys = sorted({k for m in table.values() for k in m})
    lines = ["WER / keyword recall per cell (n calls):", "",
             "| model | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    for name, cells in table.items():
        vals = []
        for k in keys:
            s = cells.get(k)
            vals.append("–" if not s else f"{s['wer']:.3f} / "
                        f"{'–' if s['keyword_recall'] is None else format(s['keyword_recall'], '.2f')} ({s['n']})")
        lines.append(f"| {name} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("benchmark", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    bench = json.loads(a.benchmark.read_text(encoding="utf-8"))
    if not any(m.get("calls") for m in bench["models"].values()):
        print("no hypotheses in this benchmark file; nothing to report", file=sys.stderr)
        return 1
    table = breakdown(bench, json.loads(EVAL_MANIFEST.read_text(encoding="utf-8")))
    out = a.out or a.benchmark.with_name(a.benchmark.stem + "_by_stufe.json")
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(markdown(table) + f"\n\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
