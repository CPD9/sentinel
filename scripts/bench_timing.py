"""Processing-time metrics for the organisers -> artifacts/metrics/timing.json + docs/assets/results/timing.png/.svg.

    # 1. transcription time per file (real decode, cache bypassed, sequential, model load reported separately)
    ssh sentinel-pod ... python scripts/pod_bench_asr.py <inference.json> <out.json> --audio-root /workspace/sentinel
    .venv/bin/python scripts/pod_bench_asr.py artifacts/manifests/inference.json <cpu.json> --device cpu \
        --compute-type int8 --ids call_049 call_050 call_026 call_034 call_052 call_061
    # 2. per-stage pipeline times on 10 dev calls, fresh LLM caches, GPU ASR decodes seeded (workers 1)
    .venv/bin/python scripts/bench_timing.py stages --scratch <dir>
    # 3. merge everything (+ the rehearsal summaries written by scripts/run_test_set.sh) and draw the figure
    .venv/bin/python scripts/bench_timing.py report --gpu <gpu.json> --cpu <cpu.json> --stages <timings.json> \
        --rehearsal <timing_summary.json> ...

Every number in timing.json comes from one of the input files (named in `sources`); nothing is extrapolated.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.timing import stats  # noqa: E402

METRICS = REPO_ROOT / "artifacts" / "metrics"
STAGE_CALLS = ["call_002", "call_005", "call_007", "call_008", "call_010",
               "call_011", "call_013", "call_015", "call_016", "call_018"]     # first 10 dev calls
STAGE_ORDER = ["asr", "analysis", "keywords", "extract", "judge", "rules", "confidence", "decide", "snippets",
               "narrate", "trigger"]


def cmd_stages(a) -> int:
    """Fresh run of 10 dev calls in a scratch artifacts dir: LLM caches empty (real extraction + judge times), the
    GPU ASR decodes copied in (so the laptop does not CPU-decode; GPU decode time comes from the ASR benchmark)."""
    scratch = a.scratch.resolve()
    if scratch.exists() and any(scratch.iterdir()):
        raise SystemExit(f"{scratch} is not empty; give a fresh folder")
    inf = {c["call_id"]: c for c in json.loads((REPO_ROOT / "artifacts/manifests/inference.json").read_text())["calls"]}
    wavs = scratch / "wavs"
    wavs.mkdir(parents=True)
    for cid in STAGE_CALLS:
        (wavs / f"{cid}.wav").symlink_to((REPO_ROOT / inf[cid]["audio_path"]).resolve())
    art = scratch / "artifacts"
    (art / "cache").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "artifacts" / "cache" / "asr", art / "cache" / "asr")
    t = scratch / "timings.json"
    r = subprocess.run([str(REPO_ROOT / "run.sh"), str(wavs), "--out", str(scratch / "out"), "--artifacts", str(art),
                        "--workers", "1", "--timings", str(t), "--run-id", "bench_stages"], cwd=REPO_ROOT)
    print(f"wrote {t}")
    return r.returncode


def _load(p: Path | None) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p else None


def cmd_report(a) -> int:
    gpu, cpu, st = _load(a.gpu), _load(a.cpu), _load(a.stages)
    reh = [_load(p) for p in a.rehearsal or []]
    gs, cs = gpu["summary"], cpu["summary"]
    asr_gpu = {
        "device": f"{gs['device']}/{gs['compute_type']}", "gpu": a.gpu_name, "model": gs["model"],
        "files": gs["files"], "model_load_s": gs["model_load_s"], "warmup_s": gs["warmup_s"],
        "decode_s_per_file": gs["decode_s"], "audio_s_per_file": gs["audio_s"], "rtf_overall": gs["rtf_overall"],
        "rtf_per_file": gs["rtf_per_file"], "vram_peak_above_baseline_mib":
            (gs["vram_peak_mib"] - gs["vram_baseline_mib"]) if gs.get("vram_baseline_mib") is not None else None,
    }
    asr_cpu = {
        "device": f"{cs['device']}/{cs['compute_type']}", "host": a.cpu_name, "model": cs["model"],
        "files": cs["files"], "call_ids": [r["call_id"] for r in cpu["files"]], "model_load_s": cs["model_load_s"],
        "warmup_s": cs["warmup_s"], "decode_s_per_file": cs["decode_s"], "audio_s_per_file": cs["audio_s"],
        "rtf_overall": cs["rtf_overall"], "rtf_per_file": cs["rtf_per_file"],
        "note": "6-file sample spread over the duration range, one file at a time, laptop otherwise idle",
    }
    stages = None
    if st:
        stages = {"calls_n": st["calls_n"], "workers": st["workers"], "wall_s": st["wall_s"],
                  "stage_errors": st["stage_errors"], "per_call_s": st["per_call_s"],
                  "stages": {k: st["stages"][k] for k in STAGE_ORDER if k in st["stages"]},
                  "note": "laptop pipeline, one call at a time, fresh LLM caches; the 'asr' row here is a cache "
                          "read of the GPU decode, its real cost is asr_gpu.decode_s_per_file"}
    rehearsal = [{k: r[k] for k in ("label", "files", "workers", "format", "audio_s_total", "pod_asr", "pipeline_wall_s",
                                    "total_s", "stage_errors", "per_call_s", "throughput_calls_per_min") if k in r}
                 for r in reh]
    ok = [r for r in rehearsal if r.get("stage_errors") == 0]
    best = min(ok, key=lambda r: r["pipeline_wall_s"]) if ok else None
    body = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "asr_gpu": asr_gpu, "asr_cpu": asr_cpu, "pipeline_stages": stages, "rehearsal": rehearsal,
        "recommended_workers": best["workers"] if best else None,
        "sources": {k: str(v) for k, v in (("gpu", a.gpu), ("cpu", a.cpu), ("stages", a.stages)) if v}
                   | {"rehearsal": [str(p) for p in a.rehearsal or []]},
    }
    out = METRICS / "timing.json"
    out.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    figure(body)
    return 0


def figure(body: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from make_figures import INK, JUDGE, MULTI, MUTED, save  # same style as the other result figures

    st = (body.get("pipeline_stages") or {}).get("stages", {})
    reh = [r for r in body.get("rehearsal") or [] if r.get("pipeline_wall_s") and r.get("label", "").count("warm") == 0]
    rows = [("ASR (A40 GPU)", body["asr_gpu"]["decode_s_per_file"], JUDGE)]
    rows += [(k, st[k], MULTI) for k in STAGE_ORDER if k in st and k != "asr" and st[k].get("median", 0) >= 0.05]
    fig, axes = plt.subplots(1, 2 if reh else 1, figsize=(11 if reh else 7.2, 0.42 * len(rows) + 1.4),
                             gridspec_kw={"width_ratios": [1.5, 1]} if reh else None)
    ax = axes[0] if reh else axes
    for i, (name, s, col) in enumerate(rows):
        ax.barh(i, s["median"], color=col, height=0.6)
        ax.plot([s["min"], s["p90"]], [i, i], color=INK, lw=1)
        ax.text(s["p90"] + 0.3, i, f"{s['median']:.1f} s (p90 {s['p90']:.1f})", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel("seconds per call (bar = median, line = min to p90)")
    pc = (body.get("pipeline_stages") or {}).get("per_call_s", {})
    ax.set_title(f"Per call, one at a time · ASR: {body['asr_gpu']['files']} calls · pipeline: "
                 f"{(body.get('pipeline_stages') or {}).get('calls_n', 0)} calls, median {pc.get('median', 0):.0f} s + ASR",
                 fontsize=9.5, color=MUTED, loc="left")
    ax.set_xlim(0, max(s["p90"] for _, s, _ in rows) * 1.45)
    ax.grid(axis="y", visible=False)
    if reh:
        bx = axes[1]
        reh = sorted(reh, key=lambda r: r["workers"])
        y = range(len(reh))
        pod = [r["pod_asr"]["total_s"] / 60 if r.get("pod_asr") else 0 for r in reh]
        pipe = [r["pipeline_wall_s"] / 60 for r in reh]
        bx.barh(y, pod, color=JUDGE, height=0.6, label="Pod ASR (FLAC upload + GPU decode)")
        bx.barh(y, pipe, left=pod, color=MULTI, height=0.6, label="pipeline on the laptop")
        for i, (a_, b_) in enumerate(zip(pod, pipe)):
            bx.text(a_ + b_ + 0.2, i, f"{a_ + b_:.1f} min", va="center", fontsize=8.5, color=INK)
        bx.set_yticks(list(y), [f"{r['workers']} workers" for r in reh])
        bx.invert_yaxis()
        bx.set_xlabel(f"minutes for {reh[0]['files']} calls ({reh[0].get('audio_s_total', 0) / 60:.0f} min of audio)")
        bx.set_title("End to end, new set of calls", fontsize=9.5, color=MUTED, loc="left")
        bx.set_xlim(0, max(a_ + b_ for a_, b_ in zip(pod, pipe)) * 1.3)
        bx.grid(axis="y", visible=False)
        bx.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=7.5, frameon=False)
    save(fig, "timing")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stages")
    s.add_argument("--scratch", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--gpu", type=Path, required=True)
    r.add_argument("--cpu", type=Path, required=True)
    r.add_argument("--stages", type=Path)
    r.add_argument("--rehearsal", type=Path, nargs="*")
    r.add_argument("--gpu-name", default="NVIDIA A40 (Runpod)")
    r.add_argument("--cpu-name", default="MacBook Air M2, 16 GB (8 cores)")
    a = ap.parse_args(argv)
    return {"stages": cmd_stages, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
