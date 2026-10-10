"""Milestone 3a: CPU-only audio analysis -> AnalysisArtifact (the UI's "Audio analysis" tab).

Per call: waveform peaks, downsampled mel spectrogram (dB), energy VAD, per-segment SNR + call-level
audio-quality score, pitch and energy contours. `turns`, `asr_confidence` and `speech_rate` need ASR and stay
empty; `feature_maps` stays "not_computed". Only `audio_quality` may later feed the confidence gate.
Every block is optional: a failing block becomes `None` + a StageError, never an exception.

Label isolation: reads only artifacts/manifests/inference.json (neutral call ids, audio paths) and the split file.

    python -m pipeline.audio_analysis --split dev            # artifacts/analysis/<call_id>/analysis.json + analysis.png
    python -m pipeline.audio_analysis --call-id call_002 --force
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

from pipeline.schemas import (Axis, AnalysisArtifact, AnalysisVersions, AudioQuality, Contour, Interval,
                              MelSpectrogram, QualitySegment, SpeechActivity, StageError, WaveformPeaks)

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_FILE = REPO_ROOT / "artifacts" / "manifests" / "inference.json"
SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
OUT_DIR = REPO_ROOT / "artifacts" / "analysis"

# --- parameters (all embedded in the version string via _params_tag) ---------------------------------
PEAK_BUCKET_S = 0.25
MEL_BANDS, MEL_FMIN, MEL_FMAX, MEL_NFFT, MEL_HOP = 40, 64.0, 8000.0, 2048, 512
MEL_BIN_S = 0.5              # output time resolution (power-averaged)
DB_MIN, DB_MAX = -80.0, 0.0
FRAME_S, HOP_S = 0.025, 0.010   # VAD / SNR frames
VAD_MIN_MARGIN_DB = 6.0         # speech threshold = floor + max(margin, 0.3*(p95-floor))
VAD_MERGE_GAP_S, VAD_MIN_LEN_S = 0.3, 0.2
SNR_MAX_DB = 60.0
SNR_LO_DB, SNR_HI_DB = 5.0, 30.0   # score = clip((snr-lo)/(hi-lo), 0, 1); heuristic mapping, not calibrated
CONTOUR_HOP_S, CONTOUR_FRAME = 0.2, 2048
PITCH_FMIN, PITCH_FMAX = 60.0, 400.0
PITCH_HOP_S, PITCH_FRAME = 0.02, 1024

ANALYSIS_VERSION = (f"audio-analysis-v1(peaks={PEAK_BUCKET_S}s,mel={MEL_BANDS}x{MEL_BIN_S}s,vad=energy,"
                    f"contour={CONTOUR_HOP_S}s,pyin={PITCH_FMIN:.0f}-{PITCH_FMAX:.0f}Hz@{PITCH_HOP_S}s)")

_TIME = Axis("time", "s")


def _r(x, n=3):
    return [None if v is None else round(float(v), n) for v in x]


# --------------------------------------------------------------------------- frames / VAD

def _frame_power(y: np.ndarray, sr: int) -> np.ndarray:
    """Mean-square power per 25 ms frame at a 10 ms hop (last partial frame zero-padded)."""
    fl, hop = int(FRAME_S * sr), int(HOP_S * sr)
    n = 1 + int(np.ceil(max(0, len(y) - fl) / hop))
    pad = np.zeros((n - 1) * hop + fl, dtype=np.float64)
    pad[:len(y)] = y
    idx = np.arange(fl)[None, :] + hop * np.arange(n)[:, None]
    return np.mean(pad[idx] ** 2, axis=1)


def _db(p: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(p + 1e-12)


def _vad_mask(power: np.ndarray) -> np.ndarray:
    d = _db(power)
    floor, top = np.percentile(d, 10), np.percentile(d, 95)
    thr = floor + max(VAD_MIN_MARGIN_DB, 0.3 * (top - floor))
    return d > thr


def _mask_to_intervals(mask: np.ndarray, duration: float) -> list[tuple[float, float]]:
    iv: list[list[float]] = []
    start = None
    for i, m in enumerate(np.append(mask, False)):
        if m and start is None:
            start = i
        elif not m and start is not None:
            iv.append([start * HOP_S, i * HOP_S + (FRAME_S - HOP_S)])
            start = None
    merged: list[list[float]] = []
    for s, e in iv:
        if merged and s - merged[-1][1] < VAD_MERGE_GAP_S:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    out = []
    for s, e in merged:
        e = min(e, duration)
        if e - s >= VAD_MIN_LEN_S:
            out.append((round(s, 3), round(e, 3)))
    return out


def _intervals_mask(intervals: list[tuple[float, float]], n: int) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    for s, e in intervals:
        m[int(s / HOP_S):int(np.ceil(e / HOP_S))] = True
    return m


def _noise_power(power: np.ndarray, speech: np.ndarray) -> float:
    nonspeech = power[~speech]
    if len(nonspeech) < 10:   # VAD found (almost) only speech: fall back to the quietest 10 % of frames
        nonspeech = np.sort(power)[:max(1, len(power) // 10)]
    return float(max(np.mean(nonspeech), 1e-12))


def _snr_db(speech_power: float, noise_power: float) -> float:
    sig = max(speech_power - noise_power, 1e-3 * noise_power)
    return float(min(10.0 * np.log10(sig / noise_power), SNR_MAX_DB))


def _score(snr_db: float) -> float:
    return float(np.clip((snr_db - SNR_LO_DB) / (SNR_HI_DB - SNR_LO_DB), 0.0, 1.0))


# --------------------------------------------------------------------------- blocks

def _waveform(y: np.ndarray, sr: int, duration: float) -> WaveformPeaks:
    per = int(round(PEAK_BUCKET_S * sr))
    nb = int(np.ceil(len(y) / per))
    pad = np.zeros(nb * per, dtype=np.float64)
    pad[:len(y)] = y
    pad[len(y):] = y[-1] if len(y) else 0.0   # no artificial zero spike at the end
    b = pad.reshape(nb, per)
    scale = max(float(np.max(np.abs(y))), 1e-9)
    return WaveformPeaks(PEAK_BUCKET_S, _r(np.clip(b.min(1) / scale, -1, 1), 4), _r(np.clip(b.max(1) / scale, -1, 1), 4),
                         {"x": _TIME, "y": Axis("amplitude", "normalised (-1..1)")})


def _mel(y: np.ndarray, sr: int, duration: float) -> MelSpectrogram:
    import librosa
    S = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=MEL_NFFT, hop_length=MEL_HOP, n_mels=MEL_BANDS,
                                       fmin=MEL_FMIN, fmax=MEL_FMAX, power=2.0)
    fps = sr / MEL_HOP
    per = int(round(MEL_BIN_S * fps))
    nb = int(np.ceil(S.shape[1] / per))
    cols = [S[:, i * per:(i + 1) * per].mean(axis=1) for i in range(nb)]
    P = np.stack(cols, axis=1)
    db = np.clip(10.0 * np.log10(P / max(P.max(), 1e-20) + 1e-20), DB_MIN, DB_MAX)
    bin_s = per * MEL_HOP / sr   # true width of a grouped column (e.g. 16 frames = 0.512 s at 16 kHz, not 0.5 s)
    starts = np.arange(nb) * bin_s
    ends = np.minimum(starts + bin_s, duration)
    times = (starts + ends) / 2
    freqs = librosa.mel_frequencies(n_mels=MEL_BANDS + 2, fmin=MEL_FMIN, fmax=MEL_FMAX)[1:-1]
    return MelSpectrogram(_r(times, 3), _r(freqs, 1), [_r(row, 1) for row in db], DB_MIN, DB_MAX,
                          {"x": _TIME, "y": Axis("frequency", "Hz (mel scale)"), "value": Axis("level", "dB")})


def _speech_activity(intervals: list[tuple[float, float]]) -> SpeechActivity:
    return SpeechActivity([Interval(s, e) for s, e in intervals], {"x": _TIME})


def _audio_quality(power: np.ndarray, intervals: list[tuple[float, float]]) -> AudioQuality:
    if not intervals:
        raise ValueError("no speech detected; quality undefined")
    speech = _intervals_mask(intervals, len(power))
    noise = _noise_power(power, speech)
    segs = []
    for i, (s, e) in enumerate(intervals, 1):
        a, b = int(s / HOP_S), max(int(s / HOP_S) + 1, int(np.ceil(e / HOP_S)))
        snr = _snr_db(float(np.mean(power[a:b])), noise)
        segs.append(QualitySegment(f"v{i:03d}", s, e, round(snr, 2), round(_score(snr), 3)))
    call_snr = _snr_db(float(np.mean(power[speech])), noise)
    return AudioQuality(round(call_snr, 2), round(_score(call_snr), 3), segs,
                        {"x": _TIME, "value": Axis("audio quality", "score 0-1")})


def _contours(y: np.ndarray, sr: int, duration: float, intervals: list[tuple[float, float]]
              ) -> tuple[Contour, Contour]:
    import librosa
    hop = int(round(CONTOUR_HOP_S * sr))
    rms = librosa.feature.rms(y=y, frame_length=CONTOUR_FRAME, hop_length=hop, center=True)[0]
    times = np.minimum(np.arange(len(rms)) * CONTOUR_HOP_S, duration)
    # strictly increasing guard: the last frame can land at/after `duration`
    keep = np.concatenate([[True], np.diff(times) > 0])
    energy = Contour(_r(times[keep], 3), _r(20.0 * np.log10(rms[keep] + 1e-6), 2),
                     {"x": _TIME, "value": Axis("energy", "dB")})
    # pyin's Viterbi needs a fine hop (a 0.2 s hop breaks its transition matrix): track at 20 ms, sample the 0.2 s grid
    ph = int(round(PITCH_HOP_S * sr))
    f0, voiced, _ = librosa.pyin(y, fmin=PITCH_FMIN, fmax=PITCH_FMAX, sr=sr, frame_length=PITCH_FRAME,
                                 hop_length=ph, center=True)
    step = int(round(CONTOUR_HOP_S / PITCH_HOP_S))
    gi = np.minimum(np.arange(len(times)) * step, len(f0) - 1)
    tt = np.arange(len(times)) * CONTOUR_HOP_S
    in_speech = np.zeros(len(times), dtype=bool)
    for s, e in intervals:
        in_speech |= (tt >= s) & (tt <= e)
    vals = [None if (not voiced[g] or not ok or np.isnan(f0[g])) else f0[g] for g, ok in zip(gi, in_speech)]
    pitch = Contour(_r(times[keep], 3), _r([v for v, k in zip(vals, keep) if k], 1),
                    {"x": _TIME, "value": Axis("pitch (F0)", "Hz")})
    return pitch, energy


# --------------------------------------------------------------------------- orchestration

def load_audio(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return y.mean(axis=1), int(sr)


def analyze_call(audio_path: str | Path, call_id: str) -> AnalysisArtifact:
    path = Path(audio_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    y, sr = load_audio(path)
    duration = round(len(y) / sr, 3)
    art = AnalysisArtifact(call_id=call_id, duration_s=duration, sample_rate=sr,
                           versions=AnalysisVersions(analysis=ANALYSIS_VERSION, asr=None))
    errors: list[StageError] = []

    def block(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # a block must never abort the call
            errors.append(StageError(f"analysis.{name}", f"{type(exc).__name__}: {exc}"))

    state: dict = {}

    def vad():
        power = _frame_power(y, sr)
        state["power"] = power
        state["intervals"] = _mask_to_intervals(_vad_mask(power), duration)
        art.speech_activity = _speech_activity(state["intervals"])

    def quality():
        art.audio_quality = _audio_quality(state["power"], state["intervals"])

    def contours():
        art.pitch, art.energy = _contours(y, sr, duration, state.get("intervals", []))

    def waveform():
        art.waveform_peaks = _waveform(y, sr, duration)

    def mel():
        art.mel_spectrogram = _mel(y, sr, duration)

    block("waveform_peaks", waveform)
    block("mel_spectrogram", mel)
    block("speech_activity", vad)
    block("audio_quality", quality)
    block("pitch", contours)
    errors.append(StageError("analysis.speech_rate", "not computed: needs ASR word counts"))
    art.stage_errors = errors
    return art


def write_analysis(art: AnalysisArtifact, out_dir: Path = OUT_DIR) -> Path:
    return save_analysis(art, out_dir)


# Blocks written by other stages into the same artifact (pipeline/asr.py). This module never computes
# them, so a CPU re-analysis must carry them over instead of dropping them.
ASR_BLOCKS = ("asr_confidence", "turns", "speech_rate")


def analysis_path(call_id: str, out_dir: Path = OUT_DIR) -> Path:
    return out_dir / call_id / "analysis.json"


def load_or_init_analysis(call_id: str, duration_s: float, sample_rate: int,
                          out_dir: Path = OUT_DIR) -> AnalysisArtifact:
    """The call's existing artifact (validated), or an empty one. Other stages merge their block into
    it and call save_analysis, so blocks written by different stages coexist."""
    p = analysis_path(call_id, out_dir)
    if p.is_file():
        art = AnalysisArtifact.from_dict(json.loads(p.read_text(encoding="utf-8")))
        if abs(art.duration_s - duration_s) > 0.05 or art.sample_rate != sample_rate:
            raise ValueError(f"{call_id}: existing analysis is for other audio "
                             f"({art.duration_s} s @ {art.sample_rate} Hz vs {duration_s} s @ {sample_rate} Hz)")
        return art
    return AnalysisArtifact(call_id=call_id, duration_s=duration_s, sample_rate=sample_rate)


def save_analysis(art: AnalysisArtifact, out_dir: Path = OUT_DIR) -> Path:
    """Validate, then write atomically (a reader never sees a half-written file)."""
    d = art.to_dict()
    errs = AnalysisArtifact.validate(d)
    if errs:
        raise ValueError(f"{art.call_id}: invalid AnalysisArtifact: {errs[:3]}")
    p = analysis_path(art.call_id, out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def _carry_over_asr(fresh: AnalysisArtifact, old: AnalysisArtifact) -> None:
    for name in ASR_BLOCKS:
        if getattr(old, name) is not None:
            setattr(fresh, name, getattr(old, name))
    fresh.versions.asr = old.versions.asr
    fresh.stage_errors += [e for e in old.stage_errors if e.stage.startswith("asr")]
    if old.speech_rate is not None:
        fresh.stage_errors = [e for e in fresh.stage_errors if e.stage != "analysis.speech_rate"]


def render_png(art: AnalysisArtifact, audio_path: str | Path, out_path: Path) -> None:
    """All lanes stacked on one shared time axis (docs/PRODUCT.md visual standard). Inspection aid only."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lanes = ["waveform", "mel", "speakers", "vad", "asr", "quality", "energy", "pitch"]
    fig, ax = plt.subplots(len(lanes), 1, sharex=True, figsize=(14, 12),
                           gridspec_kw={"height_ratios": [1.2, 2.2, 0.5, 0.5, 0.8, 1, 0.9, 0.9]})
    A = dict(zip(lanes, ax))

    def na(name: str, text: str) -> None:
        A[name].text(0.5, 0.5, text, ha="center", va="center", transform=A[name].transAxes, color="gray")
        A[name].set_yticks([])

    w = art.waveform_peaks
    if w:
        t = np.arange(len(w.min)) * w.bucket_s
        A["waveform"].fill_between(t, w.min, w.max, step="post", color="#1f77b4", lw=0)
        A["waveform"].set_ylim(-1, 1)
    else:
        na("waveform", "waveform not available")
    A["waveform"].set_ylabel("amplitude\n(norm.)")
    m = art.mel_spectrogram
    if m:
        im = A["mel"].imshow(np.array(m.db), aspect="auto", origin="lower", cmap="magma", vmin=m.db_min, vmax=m.db_max,
                             extent=[0, art.duration_s, 0, len(m.freqs_hz)])
        A["mel"].set_yticks([0, len(m.freqs_hz) - 1])
        A["mel"].set_yticklabels([f"{m.freqs_hz[0]:.0f}", f"{m.freqs_hz[-1]:.0f}"])
        cb = fig.colorbar(im, ax=A["mel"], pad=0.01, fraction=0.03)
        cb.set_label("level (dB)")
    else:
        na("mel", "mel spectrogram not available")
    A["mel"].set_ylabel("frequency\n(Hz, mel)")
    na("speakers", "speakers: not available (no ASR/diarization yet)")
    A["speakers"].set_ylabel("speakers")
    if art.speech_activity:
        for iv in art.speech_activity.intervals:
            A["vad"].axvspan(iv.start_s, iv.end_s, color="#2ca02c", alpha=0.8, lw=0)
        A["vad"].set_yticks([])
    else:
        na("vad", "speech activity not available")
    A["vad"].set_ylabel("speech\nactivity")
    na("asr", "ASR confidence: not available (no ASR yet)")
    A["asr"].set_ylabel("ASR conf.")
    q = art.audio_quality
    if q:
        for s in q.segments:
            A["quality"].hlines(s.score, s.start_s, s.end_s, color="#d62728", lw=3)
        A["quality"].axhline(q.call_score, color="k", ls="--", lw=1, label=f"call {q.call_score:.2f} (SNR {q.call_snr_db:.1f} dB)")
        A["quality"].set_ylim(0, 1.05)
        A["quality"].legend(loc="upper right", fontsize=8, title="feeds confidence gate", title_fontsize=8)
    else:
        na("quality", "audio quality not available")
    A["quality"].set_ylabel("quality\n(0-1)")
    for name, c, unit in (("energy", art.energy, "dB"), ("pitch", art.pitch, "Hz")):
        if c:
            v = np.array([np.nan if x is None else x for x in c.values], dtype=float)
            A[name].plot(c.times_s, v, color="#9467bd", lw=1)   # NaN = gap (unvoiced), not zero
        else:
            na(name, f"{name} not available")
        A[name].set_ylabel(f"{name}\n({unit})")
    ax[-1].set_xlim(0, art.duration_s)
    ax[-1].set_xlabel("time (s)")
    fig.suptitle(f"{art.call_id}  {art.duration_s:.1f} s  {art.versions.analysis}", fontsize=9)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=90)
    plt.close(fig)


def _inference_index() -> dict:
    return {c["call_id"]: c for c in json.loads(INFERENCE_FILE.read_text())["calls"]}


def run(split: str | None = None, call_ids: list[str] | None = None, force: bool = False, png: bool = True,
        out_dir: Path = OUT_DIR, allow_test: bool = False) -> list[dict]:
    index = _inference_index()
    splits = json.loads(SPLITS_FILE.read_text())["splits"]
    if call_ids is None:
        call_ids = splits[split]["call_ids"]
    locked = sorted(set(call_ids) & set(splits["test"]["call_ids"]))
    if locked and not allow_test:
        raise SystemExit(f"the test split is locked ({', '.join(locked[:3])}...); pass --allow-test only for the final run")
    rows = []
    for cid in call_ids:
        target = analysis_path(cid, out_dir)
        old = AnalysisArtifact.from_dict(json.loads(target.read_text(encoding="utf-8"))) if target.exists() else None
        if old is not None and old.versions.analysis == ANALYSIS_VERSION and not force:
            rows.append({"call_id": cid, "skipped": True})
            continue
        t0 = time.perf_counter()
        art = analyze_call(index[cid]["audio_path"], cid)
        if old is not None:
            _carry_over_asr(art, old)
        write_analysis(art, out_dir)
        if png:
            render_png(art, index[cid]["audio_path"], out_dir / cid / "analysis.png")
        dt = time.perf_counter() - t0
        rows.append({"call_id": cid, "duration_s": art.duration_s, "seconds": round(dt, 2),
                     "errors": [e.stage for e in art.stage_errors]})
        print(f"{cid}: {art.duration_s:.0f} s audio in {dt:.1f} s; stage errors: {rows[-1]['errors']}")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", choices=["dev", "holdout", "test"])
    ap.add_argument("--call-id", action="append")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-png", action="store_true")
    ap.add_argument("--allow-test", action="store_true")
    a = ap.parse_args(argv)
    if not a.split and not a.call_id:
        ap.error("give --split or --call-id")
    rows = run(a.split, a.call_id, a.force, not a.no_png, allow_test=a.allow_test)
    done = [r for r in rows if not r.get("skipped")]
    if done:
        audio, secs = sum(r["duration_s"] for r in done), sum(r["seconds"] for r in done)
        print(f"{len(done)} calls, {audio / 60:.1f} audio min in {secs:.1f} s -> {secs / (audio / 60):.2f} s per audio minute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
