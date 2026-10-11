"""Acoustic speaker clustering on the Pod with pyannote/speaker-diarization-3.1.

Runs in its own venv (/workspace/venvs/diarize, see requirements-diarize-pod.txt). Reads the neutral
inference manifest only, writes one raw file per call: {call_id, turns:[{start_s,end_s,cluster}], ...}.
Clusters are anonymous (SPEAKER_00/01); mapping them to advisor/customer happens on the laptop
(scripts/assign_speakers.py). The HF token comes from the HF cache login on the Pod and is never
passed on the command line or logged.

    /workspace/venvs/diarize/bin/python scripts/pod_diarize.py \
        --manifest artifacts/manifests/inference.json --root /workspace/sentinel --out /workspace/speakers/raw
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

MODEL = "pyannote/speaker-diarization-3.1"


def peak_vram_mb() -> int | None:
    try:
        import torch
        return int(torch.cuda.max_memory_allocated() / 2**20)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="artifacts/manifests/inference.json")
    ap.add_argument("--root", default=".", help="repo root that audio_path is relative to")
    ap.add_argument("--out", default="/workspace/speakers/raw")
    ap.add_argument("--only", nargs="*", help="call ids to run (default: all)")
    ap.add_argument("--num-speakers", type=int, default=2)
    args = ap.parse_args()

    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    calls = json.loads(Path(args.root, args.manifest).read_text())["calls"]
    if args.only:
        calls = [c for c in calls if c["call_id"] in set(args.only)]

    # torch>=2.6 loads checkpoints with weights_only=True; allowlist the few classes pyannote 3.x pickles.
    from pyannote.audio.core.task import Problem, Resolution, Specifications
    torch.serialization.add_safe_globals([torch.torch_version.TorchVersion, Problem, Resolution, Specifications])
    pipe = Pipeline.from_pretrained(MODEL)
    pipe.to(torch.device("cuda"))
    for c in calls:
        dst = out / f"{c['call_id']}.json"
        if dst.exists():
            continue
        wav, sr = sf.read(str(Path(args.root, c["audio_path"])), dtype="float32", always_2d=True)
        waveform = torch.from_numpy(wav.T.mean(axis=0, keepdims=True))
        t0 = time.time()
        diar = pipe({"waveform": waveform, "sample_rate": sr}, num_speakers=args.num_speakers)
        turns = [{"start_s": round(seg.start, 3), "end_s": round(seg.end, 3), "cluster": label}
                 for seg, _, label in diar.itertracks(yield_label=True)]
        rec = {"call_id": c["call_id"], "model": MODEL, "num_speakers": args.num_speakers,
               "duration_s": round(len(wav) / sr, 3), "runtime_s": round(time.time() - t0, 2),
               "peak_vram_mb": peak_vram_mb(), "turns": turns}
        tmp = dst.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=1))
        os.replace(tmp, dst)
        print(f"{c['call_id']}: {len(turns)} turns, {rec['runtime_s']} s", flush=True)


if __name__ == "__main__":
    main()
