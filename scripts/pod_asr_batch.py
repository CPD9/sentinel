"""ASR over the dev + holdout calls on the GPU Pod: one model load, per-call decode time (RTF) and peak VRAM.

Label-free: reads only artifacts/splits/dialogue_splits.json and artifacts/manifests/inference.json. The test split
is read only with --allow-test. Transcripts, analysis blocks and the decode cache go where pipeline/asr.py puts them.

    python scripts/pod_asr_batch.py --model large-v3-turbo --splits dev holdout [--compute-type float16] [--force]

Writes artifacts/metrics/pod_asr_<model>.json. Decode time excludes audio analysis (librosa) and file writing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import asr  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402


def vram_used_mib() -> int | None:
    if not shutil.which("nvidia-smi"):
        return None
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


class VramPeak:
    def __init__(self, every_s: float = 0.5):
        self.peak, self._stop, self._every = 0, threading.Event(), every_s
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self._every):
            self.peak = max(self.peak, vram_used_mib() or 0)

    def __enter__(self):
        self.peak = vram_used_mib() or 0
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()
        self.peak = max(self.peak, vram_used_mib() or 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--splits", nargs="+", choices=("dev", "holdout", "test"), default=["dev", "holdout"],
                    help="test (Testset_30, cleared by Outcept for tuning) needs --allow-test")
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    if "test" in a.splits and not a.allow_test:
        ap.error("--splits test needs --allow-test (Testset_30, cleared by Outcept for tuning)")

    splits = json.loads((REPO_ROOT / "artifacts/splits/dialogue_splits.json").read_text(encoding="utf-8"))["splits"]
    inf = {c["call_id"]: c for c in json.loads((REPO_ROOT / "artifacts/manifests/inference.json").read_text(encoding="utf-8"))["calls"]}
    ids = [i for s in a.splits for i in splits[s]["call_ids"]]
    if a.limit:
        ids = ids[:a.limit]

    model_dir, asr_model = asr.resolve_model(a.model)
    base = vram_used_mib()
    t0 = time.perf_counter()
    asr.load_model(model_dir, a.device, a.compute_type)
    load_s = time.perf_counter() - t0
    print(f"model {asr_model} loaded in {load_s:.1f} s on {a.device}/{a.compute_type}; VRAM used {vram_used_mib()} MiB (before: {base})",
          flush=True)

    decode_s: list[float] = []
    real_decode = asr.decode

    def timed(model, path, *args, **kw):
        t = time.perf_counter()
        out = real_decode(model, path, *args, **kw)
        decode_s.append(time.perf_counter() - t)
        return out
    asr.decode = timed

    rows, failed = [], []
    with VramPeak() as vp:
        for cid in ids:
            decode_s.clear()
            t = time.perf_counter()
            try:
                tr = asr.transcribe(inf[cid]["audio_path"], cid, model_spec=a.model, device=a.device,
                                    compute_type=a.compute_type, force=a.force)
            except Exception as exc:                        # one bad call must not stop the batch
                failed.append({"call_id": cid, "error": f"{type(exc).__name__}: {exc}"[:300]})
                print(f"{cid}: FAILED {failed[-1]['error']}", flush=True)
                continue
            dur = inf[cid]["duration_s"]
            d = decode_s[0] if decode_s else None          # None = decode cache hit
            rows.append({"call_id": cid, "duration_s": dur, "segments": len(tr.segments), "decode_s": d,
                         "rtf": round(d / dur, 4) if d else None, "wall_s": round(time.perf_counter() - t, 2)})
            print(f"{cid}: {len(tr.segments):3d} segs {dur:6.1f} s audio, decode {d if d is None else round(d, 1)} s"
                  f"{'' if d is None else f' (RTF {d / dur:.3f})'}", flush=True)
    live = [r for r in rows if r["decode_s"]]
    summary = {
        "model": asr_model, "device": a.device, "compute_type": a.compute_type, "splits": a.splits,
        "calls": len(rows), "failed": len(failed), "cached": len(rows) - len(live), "model_load_s": round(load_s, 1),
        "audio_s_decoded": round(sum(r["duration_s"] for r in live), 1),
        "decode_s_total": round(sum(r["decode_s"] for r in live), 1),
        "rtf_overall": round(sum(r["decode_s"] for r in live) / sum(r["duration_s"] for r in live), 4) if live else None,
        "vram_baseline_mib": base, "vram_peak_mib": vp.peak,
        "vram_peak_above_baseline_mib": vp.peak - base if base is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(), "host": asr.socket.gethostname()}
    out = REPO_ROOT / "artifacts" / "metrics" / f"pod_asr_{a.model}.json"
    write_json_atomic(out, {"summary": summary, "calls": rows, "failed": failed})
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
