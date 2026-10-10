"""CLI: run the pipeline over a folder of WAVs, or over a split. No API or web app needed.

    ./run.sh <wav_folder> [--transcripts asr|reference] [--no-llm] [--out out]
    ./run.sh --split dev --transcripts reference --no-llm --predictions     # dev evaluation without ASR / LLM

Writes <out>/results.json (a RunResult, accepted by `python -m pipeline.evaluate --pred`), <out>/results/<id>.json,
<out>/snippets/<id>/*.wav and <out>/triggers/ (DRY-RUN unless TRIGGER_URL is set).

Call ids: a WAV whose file name appears in artifacts/manifests/inference.json gets its neutral id (call_017).
Any other file gets call_xNNN by sorted order; the mapping is written to <out>/id_map.json and the original
name is never passed to the pipeline. This reads inference.json only, never evaluation.json or label files.
--transcripts reference uses the organizer scripts (artifacts/manifests/reference_transcripts.json).
--no-llm skips extraction on purpose (facts = []): an explicit ablation, not a stage error. Without it, a missing
pipeline.extract or an unreachable LLM_BASE_URL gives stage_error -> review.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import process_call  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.schemas import MODES, RunResult  # noqa: E402

INFERENCE = REPO_ROOT / "artifacts" / "manifests" / "inference.json"
SPLITS = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
PRED_DIR = REPO_ROOT / "artifacts" / "predictions"


def plan_jobs(folder: Path | None, split: str | None, allow_test: bool) -> tuple[list[tuple[str, Path]], dict[str, str]]:
    """[(call_id, audio_path)] and the name -> neutral id map for files not in inference.json."""
    index = {c["call_id"]: c for c in json.loads(INFERENCE.read_text(encoding="utf-8"))["calls"]} if INFERENCE.is_file() else {}
    locked = set(json.loads(SPLITS.read_text(encoding="utf-8"))["splits"]["test"]["call_ids"]) if SPLITS.is_file() else set()
    if split:
        ids = json.loads(SPLITS.read_text(encoding="utf-8"))["splits"][split]["call_ids"]
        jobs = [(i, REPO_ROOT / index[i]["audio_path"]) for i in ids]
        id_map: dict[str, str] = {}
    else:
        by_name = {Path(c["audio_path"]).name: cid for cid, c in index.items()}
        jobs, id_map, n = [], {}, 0
        for wav in sorted(Path(folder).glob("*.wav")):
            if wav.name in by_name:
                jobs.append((by_name[wav.name], wav))
            else:
                n += 1
                cid = f"call_x{n:03d}"
                id_map[wav.name] = cid
                jobs.append((cid, wav))
    hit = sorted(i for i, _ in jobs if i in locked)
    if hit and not allow_test:
        raise SystemExit(f"the test split is locked ({', '.join(hit[:3])}...); pass --allow-test only for the final run")
    return jobs, id_map


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path, help="folder with .wav files")
    ap.add_argument("--split", choices=("dev", "holdout", "test"), help="run a split from dialogue_splits.json instead")
    ap.add_argument("--transcripts", choices=MODES, default="asr")
    ap.add_argument("--no-llm", action="store_true", help="skip extraction deliberately (keywords + rules only)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "out")
    ap.add_argument("--run-id")
    ap.add_argument("--predictions", action="store_true", help="also write artifacts/predictions/<run_id>.json")
    ap.add_argument("--allow-test", action="store_true")
    a = ap.parse_args(argv)
    if bool(a.folder) == bool(a.split):
        ap.error("give exactly one of <wav_folder> or --split")
    if a.folder and not a.folder.is_dir():
        ap.error(f"not a folder: {a.folder}")

    jobs, id_map = plan_jobs(a.folder, a.split, a.allow_test)
    if not jobs:
        print("no .wav files found", file=sys.stderr)
        return 1
    out = a.out
    run_id = a.run_id or "_".join(["pipeline", a.transcripts, *(["nollm"] if a.no_llm else []), a.split or "folder"])
    if id_map:
        write_json_atomic(out / "id_map.json", {"note": "original file name -> neutral call id; never passed to the pipeline",
                                                "map": id_map})

    calls, t0 = [], time.perf_counter()
    for cid, wav in jobs:
        t1 = time.perf_counter()
        try:
            d = process_call(str(wav), cid, transcripts=a.transcripts, no_llm=a.no_llm, out_dir=out)
        except Exception as exc:     # only an invalid call id / argument can get here; keep the batch going
            print(f"{cid}: process_call raised {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        calls.append(d)
        errs = ",".join(e["stage"] for e in d["stage_errors"]) or "-"
        print(f"{cid}: {d['decision']:8s} risk {d['risk_score']:.2f} conf "
              f"{'n/a' if d['confidence'] is None else format(d['confidence'], '.2f')} "
              f"findings {len(d['findings'])} errors {errs} ({time.perf_counter() - t1:.1f} s)")

    notes = [f"transcripts: {a.transcripts}"]
    if a.no_llm:
        notes.insert(0, "NO LLM: extraction skipped on purpose; decisions come from keywords + rules only")
    if a.transcripts == "reference":
        notes.append("reference transcripts: no ASR errors, no timestamps, no snippets")
    notes.append("template narrative, no LLM")
    notes.append("trigger: " + ("sent to TRIGGER_URL" if __import__("os").environ.get("TRIGGER_URL") else "DRY-RUN, nothing sent"))
    run = RunResult(run_id=run_id, mode=a.transcripts, system="pipeline",
                    provider="keywords+rules (no LLM)" if a.no_llm else "pipeline (LLM extraction)",
                    created_at=datetime.now(timezone.utc).isoformat(), calls=[_cr(d) for d in calls], notes=notes)
    body = run.to_dict()
    write_json_atomic(out / "results.json", body)
    if a.predictions:
        write_json_atomic(PRED_DIR / f"{run_id}.json", body)
    counts = {k: sum(d["decision"] == k for d in calls) for k in ("alarm", "review", "no_alert")}
    print(f"\n{len(calls)} calls in {time.perf_counter() - t0:.1f} s: {counts}\nwrote {out / 'results.json'}"
          + (f" and {PRED_DIR / (run_id + '.json')}" if a.predictions else ""))
    return 0


def _cr(d: dict):
    from pipeline.schemas import CallResult
    return CallResult.from_dict(d)


if __name__ == "__main__":
    sys.exit(main())
