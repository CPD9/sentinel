"""Transcription-time benchmark: a real decode of every call, cache bypassed, sequential, one model load.

    python scripts/pod_bench_asr.py <manifest.json> <out.json> [--device cuda --compute-type float16] [--ids ...]

Reads only the neutral inference manifest (call_id, audio_path, duration_s); never reads or writes the ASR cache.
Model load and one warm-up decode (first 10 s of the first file) are timed and reported separately, so the per-file
numbers are steady-state decode times. Runs on the Pod (GPU) and on the laptop (CPU sample) with the same code;
scripts/bench_timing.py drives both and merges the results into artifacts/metrics/timing.json.
"""
from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import asr  # noqa: E402
from pipeline.timing import stats  # noqa: E402
from scripts.pod_asr_batch import VramPeak, vram_used_mib  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--cpu-threads", type=int, default=0, help="CPU only; 0 = ctranslate2 default")
    ap.add_argument("--ids", nargs="*", help="subset of call ids (default: all in the manifest)")
    ap.add_argument("--audio-root", type=Path, help="resolve relative audio_path against this dir")
    a = ap.parse_args(argv)

    calls = json.loads(a.manifest.read_text(encoding="utf-8"))["calls"]
    if a.ids:
        keep = set(a.ids)
        calls = [c for c in calls if c["call_id"] in keep]
    root = a.audio_root or REPO_ROOT

    model_dir, asr_model = asr.resolve_model(a.model)
    base = vram_used_mib() if a.device == "cuda" else None
    t0 = time.perf_counter()
    from faster_whisper import WhisperModel
    model = WhisperModel(model_dir, device=a.device, compute_type=a.compute_type,
                         **({"cpu_threads": a.cpu_threads} if a.cpu_threads else {}))
    load_s = time.perf_counter() - t0

    import soundfile as sf
    first = Path(calls[0]["audio_path"])
    first = first if first.is_absolute() else root / first
    clip, sr = sf.read(str(first), frames=10 * 16000, dtype="float32")
    t0 = time.perf_counter()
    segs, _ = model.transcribe(clip, **asr.DECODE)
    list(segs)
    warmup_s = time.perf_counter() - t0
    print(f"{asr_model} on {a.device}/{a.compute_type}: load {load_s:.1f} s, warm-up {warmup_s:.1f} s", flush=True)

    rows, failed = [], []
    with (VramPeak() if a.device == "cuda" else _Null()) as vp:
        for c in calls:
            p = Path(c["audio_path"])
            p = p if p.is_absolute() else root / p
            t = time.perf_counter()
            try:
                raw = asr.decode(model, p)
            except Exception as exc:                        # one bad file must not stop the benchmark
                failed.append({"call_id": c["call_id"], "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            d = time.perf_counter() - t
            rows.append({"call_id": c["call_id"], "duration_s": c["duration_s"], "decode_s": round(d, 3),
                         "rtf": round(d / c["duration_s"], 4), "segments": len(raw["segments"])})
            print(f"{c['call_id']}: {c['duration_s']:6.1f} s audio, decode {d:6.2f} s (RTF {d / c['duration_s']:.3f})",
                  flush=True)

    dec = [r["decode_s"] for r in rows]
    aud = [r["duration_s"] for r in rows]
    summary = {
        "model": asr_model, "device": a.device, "compute_type": a.compute_type, "decode": asr.DECODE,
        "files": len(rows), "failed": len(failed), "model_load_s": round(load_s, 2), "warmup_s": round(warmup_s, 2),
        "decode_s": stats(dec), "audio_s": stats(aud),
        "audio_s_total": round(sum(aud), 1), "decode_s_total": round(sum(dec), 1),
        "rtf_overall": round(sum(dec) / sum(aud), 4) if aud else None, "rtf_per_file": stats([r["rtf"] for r in rows]),
        "vram_baseline_mib": base, "vram_peak_mib": getattr(vp, "peak", None),
        "host": socket.gethostname(), "platform": platform.platform(), "processor": platform.processor(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "sequential real decode with pipeline.asr.DECODE, cache bypassed; model load and one 10 s warm-up "
                  "decode excluded from per-file times and reported separately",
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"summary": summary, "files": rows, "failed": failed}, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("files", "model_load_s", "warmup_s", "decode_s", "rtf_overall")}))
    return 1 if failed else 0


class _Null:
    peak = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    sys.exit(main())
