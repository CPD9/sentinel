"""Step 1: ASR with faster-whisper (self-hosted, CTranslate2) -> Transcript + AnalysisArtifact.asr_confidence.

The checkpoint is whatever `ASR_MODEL_PATH` points to: a local CTranslate2 directory (e.g. a converted
Swiss German fine-tune under artifacts/models/) or a faster-whisper model name. scripts/benchmark_asr.py
picks it. No cloud ASR.

  transcribe(audio_path, call_id) -> Transcript         cached by audio hash + model + decode settings
  run_stage(audio_path, call_id)  -> (Transcript | None, [StageError])   never raises; for process_call

Writes artifacts/transcripts/<call_id>.json and merges `asr_confidence` (+ duration/sample rate) into
artifacts/analysis/<call_id>/analysis.json, keeping the blocks other stages wrote. Speakers stay
"unknown" until pipeline/diarize.py.

    python -m pipeline.asr artifacts/audio/call_017.wav --call-id call_017 [--device cpu] [--force]
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

from pipeline.llm import load_env
from pipeline.schemas import (AsrConfidence, AsrConfidencePoint, Axis, StageError, Transcript,
                              TranscriptSegment)

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / "artifacts" / "cache" / "asr"
MODEL_REVISIONS_FILE = REPO_ROOT / "artifacts" / "cache" / "model_revisions.json"
TRANSCRIPTS_DIR = REPO_ROOT / "artifacts" / "transcripts"
ASR_VERSION = "asr-v1"

# Fixed decode settings, shared with the benchmark so the bake-off measures what the pipeline runs.
DECODE = {
    "language": "de",
    "task": "transcribe",
    "beam_size": 5,
    "temperature": 0.0,
    "vad_filter": True,
    "word_timestamps": True,
    "condition_on_previous_text": False,   # avoids repetition loops on long calls
}


class AsrError(RuntimeError):
    pass


# --------------------------------------------------------------------------- model

def resolve_model(spec: str | None = None) -> tuple[str, str]:
    """(local model dir, "<name>@<revision>") for a CTranslate2 dir or a faster-whisper model name."""
    load_env()
    spec = spec or os.environ.get("ASR_MODEL_PATH")
    if not spec:
        raise AsrError("ASR_MODEL_PATH is not set")
    p = Path(spec).expanduser()
    if not p.is_dir() and (REPO_ROOT / spec).is_dir():
        p = REPO_ROOT / spec
    if not p.is_dir():
        from faster_whisper.utils import download_model
        p = Path(download_model(spec))
    return str(p), f"{_model_name(spec, p)}@{_model_revision(p)}"


def _model_name(spec: str, path: Path) -> str:
    if "/snapshots/" in str(path):          # HF cache: .../models--org--name/snapshots/<commit>
        return path.parent.parent.name.removeprefix("models--").replace("--", "/")
    return Path(spec).name if Path(spec).expanduser().is_dir() else spec


def _model_revision(path: Path, memo_file: Path | None = None) -> str:
    """HF snapshot -> its commit. Local dir -> sha256 over every file's name + content (weights included),
    so a checkpoint replaced in place gets a new revision. Per-file hashes are memoised by
    (path, size, mtime_ns, inode) because hashing a 3 GB model.bin on every call is slow."""
    if path.parent.name == "snapshots":
        return path.name[:12]
    memo_file = memo_file or MODEL_REVISIONS_FILE
    try:
        memo = json.loads(memo_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        memo = {}
    h, changed = hashlib.sha256(), False
    for f in sorted(path.iterdir()):
        if not f.is_file():
            continue
        st = f.stat()
        key = f"{f.resolve()}|{st.st_size}|{st.st_mtime_ns}|{st.st_ino}"
        if key not in memo:
            memo[key], changed = _sha256(f), True
        h.update(f.name.encode())
        h.update(memo[key].encode())
    if changed:
        memo_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = memo_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(memo, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(memo_file)
    return "sha-" + h.hexdigest()[:12]


def default_device() -> tuple[str, str]:
    import ctranslate2
    return ("cuda", "float16") if ctranslate2.get_cuda_device_count() > 0 else ("cpu", "int8")


@functools.lru_cache(maxsize=2)
def load_model(model_dir: str, device: str, compute_type: str):
    """One model per process (one GPU job at a time, docs/API.md)."""
    from faster_whisper import WhisperModel
    return WhisperModel(model_dir, device=device, compute_type=compute_type)


# --------------------------------------------------------------------------- decode

def audio_info(path: Path) -> tuple[float, int]:
    import soundfile as sf
    info = sf.info(str(path))
    return round(info.frames / info.samplerate, 3), int(info.samplerate)


def decode(model, audio_path: Path, decode: dict = DECODE) -> dict:
    """Raw faster-whisper output as plain JSON (segments with words). Used by the benchmark too."""
    segments, info = model.transcribe(str(audio_path), **decode)
    out = []
    for s in segments:   # generator: decoding happens here
        out.append({
            "start": float(s.start), "end": float(s.end), "text": s.text.strip(),
            "avg_logprob": float(s.avg_logprob), "no_speech_prob": float(s.no_speech_prob),
            "words": [{"start": float(w.start), "end": float(w.end), "word": w.word,
                       "probability": float(w.probability)} for w in (s.words or [])],
        })
    return {"language": info.language, "language_probability": float(info.language_probability),
            "segments": out}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def timing_config(device: str, compute_type: str) -> dict:
    """Where a decode was timed. Caches from teammates' CPUs and GPUs get merged, so an elapsed time
    is only comparable when all three match (the hypothesis itself is valid everywhere)."""
    return {"device": device, "compute_type": compute_type, "host": socket.gethostname()}


def write_cache(path: Path, asr_model: str, raw: dict, elapsed_s: float, timing: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"asr_model": asr_model, "decode": DECODE, "asr_version": ASR_VERSION,
                               **timing, "elapsed_s": round(elapsed_s, 3), "raw": raw},
                              ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def cached_elapsed(entry: dict, timing: dict) -> float | None:
    """The entry's decode time if it was measured in exactly this timing config, else None."""
    same = all(entry.get(k) == v for k, v in timing.items())
    return entry.get("elapsed_s") if same else None


def cache_key(audio_sha: str, asr_model: str, device: str, compute_type: str, decode: dict = DECODE) -> str:
    """Hypotheses are keyed by inference config too: CPU/int8 and GPU/float16 can decode different text."""
    blob = json.dumps({"audio": audio_sha, "model": asr_model, "device": device, "compute_type": compute_type,
                       "decode": decode, "v": ASR_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


# --------------------------------------------------------------------------- conversion

def to_transcript(call_id: str, raw: dict, duration_s: float, asr_model: str) -> Transcript:
    """Clamp times into [0, duration]; drop empty or zero-length segments (noted, never silent)."""
    segs, notes = [], []
    for s in raw["segments"]:
        start, end = max(0.0, s["start"]), min(duration_s, s["end"])
        if not s["text"] or end <= start:
            notes.append(f"dropped segment {s['start']:.2f}-{s['end']:.2f} s "
                         f"({'empty text' if not s['text'] else 'zero length after clamping'})")
            continue
        segs.append(TranscriptSegment(
            id=f"S{len(segs) + 1:04d}", speaker="unknown", text=s["text"],
            start_s=round(start, 3), end_s=round(end, 3),
            avg_logprob=round(min(0.0, s["avg_logprob"]), 4),
            no_speech_prob=round(min(1.0, max(0.0, s["no_speech_prob"])), 4)))
    notes.append(f"language={raw.get('language')} p={raw.get('language_probability', 0):.3f}")
    return Transcript(call_id=call_id, mode="asr", segments=segs, asr_model=asr_model,
                      duration_s=duration_s, notes=notes)


def asr_confidence(t: Transcript) -> AsrConfidence:
    return AsrConfidence(
        [AsrConfidencePoint(s.id, s.start_s, s.end_s, s.avg_logprob, s.no_speech_prob) for s in t.segments],
        {"x": Axis("time", "s"), "value": Axis("ASR confidence", "avg log-prob")})


def write_outputs(t: Transcript, sample_rate: int, transcripts_dir: Path = TRANSCRIPTS_DIR,
                  analysis_dir: Path | None = None, audio_sha256: str | None = None) -> tuple[Path, Path]:
    from pipeline import audio_analysis as aa
    d = t.to_dict()
    errs = Transcript.validate(d)
    if errs:
        raise AsrError(f"{t.call_id}: invalid Transcript: {errs[:3]}")
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    tp = transcripts_dir / f"{t.call_id}.json"
    tp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    analysis_dir = analysis_dir or aa.OUT_DIR
    art = aa.load_or_init_analysis(t.call_id, t.duration_s, sample_rate, analysis_dir, audio_sha256)
    art.asr_confidence = asr_confidence(t)
    art.versions.asr = t.asr_model
    art.stage_errors = [e for e in art.stage_errors if not e.stage.startswith("asr")]
    return tp, aa.save_analysis(art, analysis_dir)


# --------------------------------------------------------------------------- entry points

def transcribe(audio_path: str | Path, call_id: str, model_spec: str | None = None,
               device: str | None = None, compute_type: str | None = None, force: bool = False,
               cache_dir: Path = CACHE_DIR, transcripts_dir: Path = TRANSCRIPTS_DIR,
               analysis_dir: Path | None = None) -> Transcript:
    path = Path(audio_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        raise AsrError(f"audio not found: {path}")
    duration_s, sample_rate = audio_info(path)
    model_dir, asr_model = resolve_model(model_spec)
    audio_sha = _sha256(path)
    device = device or default_device()[0]
    compute_type = compute_type or ("float16" if device == "cuda" else "int8")
    cp = cache_dir / f"{cache_key(audio_sha, asr_model, device, compute_type)}.json"
    if cp.is_file() and not force:
        raw = json.loads(cp.read_text(encoding="utf-8"))["raw"]
    else:
        t0 = time.perf_counter()
        raw = decode(load_model(model_dir, device, compute_type), path)
        write_cache(cp, asr_model, raw, time.perf_counter() - t0, timing_config(device, compute_type))
    t = to_transcript(call_id, raw, duration_s, asr_model)
    if not t.segments:
        raise AsrError(f"{call_id}: ASR produced no usable segments")
    write_outputs(t, sample_rate, transcripts_dir, analysis_dir, audio_sha)
    return t


def run_stage(audio_path: str | Path, call_id: str, **kw) -> tuple[Transcript | None, list[StageError]]:
    """For process_call: a failed ASR is a recorded stage error, never an empty transcript."""
    try:
        return transcribe(audio_path, call_id, **kw), []
    except Exception as exc:
        return None, [StageError("asr", f"{type(exc).__name__}: {exc}")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("audio")
    ap.add_argument("--call-id", required=True)
    ap.add_argument("--model", help="overrides ASR_MODEL_PATH")
    ap.add_argument("--device", choices=["cpu", "cuda"])
    ap.add_argument("--compute-type")
    ap.add_argument("--force", action="store_true", help="ignore the cache")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    t, errors = run_stage(a.audio, a.call_id, model_spec=a.model, device=a.device,
                          compute_type=a.compute_type, force=a.force)
    if errors:
        print(f"{a.call_id}: ASR failed: {errors[0].message}", file=sys.stderr)
        return 1
    print(f"{a.call_id}: {len(t.segments)} segments, {t.duration_s:.0f} s audio, {t.asr_model}, "
          f"{time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
