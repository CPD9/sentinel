"""Step 10: ffmpeg cut of each evidence passage +-10 s, clamped to [0, audio duration].

    cut_snippets(audio_path, call_id, findings, duration_s, out_dir) -> list[StageError]

Sets `Evidence.snippet_path` (repo-relative when inside the repo) on every evidence item that has a
valid time span. Each cut is written under a temp name, validated with ffprobe (playable, duration
close to the requested window) and only then moved into place. A failure is a StageError for the
call; it never changes the decision. Reference mode has no timestamps, so nothing is cut there.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from pipeline.schemas import Finding, StageError

REPO_ROOT = Path(__file__).resolve().parents[1]
PAD_S = 10.0
DURATION_TOLERANCE_S = 0.25


class SnippetError(RuntimeError):
    pass


def snippet_window(start_s: float, end_s: float, duration_s: float, pad_s: float = PAD_S) -> tuple[float, float]:
    """[start - pad, end + pad] clamped into [0, duration]. Raises SnippetError if the span is unusable."""
    if not (start_s is not None and end_s is not None and 0 <= start_s < end_s):
        raise SnippetError(f"need 0 <= start < end, got {start_s}..{end_s}")
    if start_s >= duration_s:
        raise SnippetError(f"evidence starts at {start_s} s, after the end of the audio ({duration_s} s)")
    lo, hi = max(0.0, start_s - pad_s), min(duration_s, end_s + pad_s)
    if not lo < hi:
        raise SnippetError(f"empty window after clamping: {lo}..{hi}")
    return round(lo, 3), round(hi, 3)


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        d = float(r.stdout.strip())
    except ValueError:
        raise SnippetError(f"ffprobe cannot read {path.name}: {r.stderr.strip()[:200]}") from None
    if r.returncode != 0 or d <= 0:
        raise SnippetError(f"{path.name} is not playable (ffprobe rc={r.returncode}, duration={d})")
    return d


def cut(audio_path: Path, lo: float, hi: float, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.stem}.", suffix=".wav", dir=dest.parent)
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-to", f"{hi:.3f}", "-i", str(audio_path),
                            "-c:a", "pcm_s16le", str(tmp_path)], capture_output=True, text=True)
        if r.returncode != 0:
            raise SnippetError(f"ffmpeg failed: {r.stderr.strip()[:300]}")
        got = probe_duration(tmp_path)
        if abs(got - (hi - lo)) > DURATION_TOLERANCE_S:
            raise SnippetError(f"cut is {got:.2f} s, expected {hi - lo:.2f} s")
        os.replace(tmp_path, dest)
    finally:
        tmp_path.unlink(missing_ok=True)


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def cut_snippets(audio_path: str | Path, call_id: str, findings: list[Finding], duration_s: float | None,
                 out_dir: Path) -> list[StageError]:
    """Cut one snippet per evidence item that has timestamps. Returns StageErrors (empty = all fine)."""
    audio = Path(audio_path)
    if not audio.is_absolute():
        audio = REPO_ROOT / audio
    errors: list[StageError] = []
    if duration_s is None:
        try:
            duration_s = probe_duration(audio)
        except SnippetError as e:
            return [StageError("snippets", str(e))]
    for fi, f in enumerate(findings):
        crit = re.sub(r"\W+", "_", f.criterion)
        for ei, ev in enumerate(f.evidence):
            if ev.start_s is None or ev.end_s is None:
                continue
            name = f"{crit}_{fi}_{ei}.wav"
            try:
                lo, hi = snippet_window(ev.start_s, ev.end_s, duration_s)
                dest = Path(out_dir) / call_id / name
                cut(audio, lo, hi, dest)
                ev.snippet_path = _rel(dest)
            except Exception as exc:
                ev.snippet_path = None
                errors.append(StageError("snippets", f"{name}: {type(exc).__name__}: {exc}"))
    return errors
