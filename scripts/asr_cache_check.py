"""One ASR model for the Pod and the pipeline, and a loud check that the Pod's decodes will be used.

    python scripts/asr_cache_check.py id                                   # -> "<spec>\t<name>@<revision>"
    python scripts/asr_cache_check.py check <wav_folder> <cache_dir> <name@revision>

`id` resolves the model exactly as the pipeline does (pipeline.asr.resolve_model: ASR_MODEL_PATH, else .env, else
DEFAULT_ASR_MODEL) and prints the Hugging Face spec to give the Pod plus the full id (name@revision) the cache keys
are built from. A local checkpoint directory cannot be reproduced on the Pod, so it exits 2 instead of guessing.

`check` recomputes, for every WAV, the GPU cache key the pipeline will look up (pipeline.asr.cache_key with
cuda/float16) and exits 3 listing the files whose decode is missing. Without this, a key mismatch (other model,
other revision, other decode settings) would make ./run.sh silently re-decode everything on the laptop CPU.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import asr  # noqa: E402


def model_id() -> tuple[str, str]:
    model_dir, mid = asr.resolve_model(None)
    if "/snapshots/" not in model_dir:
        raise SystemExit(f"ASR model is a local directory ({model_dir}): the Pod cannot load the same model. "
                         f"Set ASR_MODEL_PATH={asr.DEFAULT_ASR_MODEL} for a run that uses the Pod.")
    return mid.rsplit("@", 1)[0], mid


def missing(wav_folder: Path, cache_dir: Path, mid: str) -> list[str]:
    return [w.name for w in sorted(wav_folder.glob("*.wav"))
            if not (cache_dir / f"{asr.cache_key(asr._sha256(w), mid, *asr.GPU_DECODE)}.json").is_file()]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["id"]:
        spec, mid = model_id()
        print(f"{spec}\t{mid}")
        return 0
    if argv[:1] == ["check"] and len(argv) == 4:
        miss = missing(Path(argv[1]), Path(argv[2]), argv[3])
        if miss:
            print(f"ASR CACHE MISMATCH: {len(miss)} file(s) have no GPU decode under the pipeline's key for {argv[3]} "
                  f"(the run would re-decode them on the CPU): {', '.join(miss[:5])}{' ...' if len(miss) > 5 else ''}",
                  file=sys.stderr)
            return 3
        print(f"ASR cache check ok: every WAV has its GPU decode for {argv[3]}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
