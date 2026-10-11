"""Pod-side: decode every WAV in a folder on the GPU into an ASR cache dir (one model load, faster-whisper float16).

    python scripts/pod_asr_folder.py <wav_folder> <cache_dir> [--model large-v3-turbo]

Writes <cache_dir>/<key>.json with the same key as pipeline.asr.transcribe (audio sha256 + model + device + decode
settings), so a laptop run whose artifacts dir holds these files reuses the GPU hypotheses (pipeline/asr.py prefers
a GPU/float16 decode on any host) and does no CPU decoding. Driven by scripts/pod_asr_folder.sh.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import asr  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("cache_dir", type=Path)
    ap.add_argument("--model", default="large-v3-turbo")
    a = ap.parse_args(argv)
    model_dir, asr_model = asr.resolve_model(a.model)
    model = asr.load_model(model_dir, "cuda", "float16")
    a.cache_dir.mkdir(parents=True, exist_ok=True)
    wavs = sorted(a.folder.glob("*.wav"))
    t_all = time.perf_counter()
    for w in wavs:
        cp = a.cache_dir / f"{asr.cache_key(asr._sha256(w), asr_model, 'cuda', 'float16')}.json"
        if cp.is_file():
            continue
        t0 = time.perf_counter()
        raw = asr.decode(model, w)
        asr.write_cache(cp, asr_model, raw, time.perf_counter() - t0, asr.timing_config("cuda", "float16"))
        print(f"{w.name}: {time.perf_counter() - t0:.1f} s", flush=True)
    print(f"{len(wavs)} files in {time.perf_counter() - t_all:.1f} s with {asr_model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
