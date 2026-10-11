"""Pod-side language ID (and optional Whisper-encoder embeddings) for the language-routing map. Display only.

    # per speaker of each call: speaker turns (sentinel-runs/speakers/<id>.json) -> <out>/<call_id>.json
    python scripts/pod_langid.py calls <inference.json> <speakers_dir> <out_dir> --audio-root /workspace/sentinel [--embed]
    # validation clips (FLEURS fr/it/de, SwissDial): one detection per clip -> <out>.json (+ <out>.npz with --embed)
    python scripts/pod_langid.py clips <clips.json> <out.json> [--embed]

Language detection is faster-whisper's `detect_language` on <=30 s windows (one forward pass of the encoder and the
language token), so it is cheap next to a full decode. A speaker's turns of >= 1 s are concatenated in time order and
cut into <=30 s windows; the window distributions are averaged weighted by their speech seconds. Whisper has no
Romansh, so `rm` can never be detected (the output says so). --embed also stores the mean-pooled encoder output of
each window / clip (1280-d) for the SwissDial research classifier (scripts/dialect_research.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import asr  # noqa: E402

SR = 16000
WIN_S = 30.0
MIN_TURN_S = 1.0


def load_model(spec: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    model_dir, name = asr.resolve_model(spec)
    return WhisperModel(model_dir, device=device, compute_type=compute_type), name


def detect(model, audio: np.ndarray) -> dict[str, float]:
    _, _, all_probs = model.detect_language(audio=audio)
    return {lang: float(p) for lang, p in all_probs}


def embed(model, audio: np.ndarray) -> np.ndarray:
    """Mean over time of the encoder output for one <=30 s window (padded like Whisper does)."""
    import ctranslate2
    feats = model.feature_extractor(audio)[:, : model.feature_extractor.nb_max_frames]
    if feats.shape[-1] < model.feature_extractor.nb_max_frames:
        feats = np.pad(feats, ((0, 0), (0, model.feature_extractor.nb_max_frames - feats.shape[-1])))
    enc = model.encode(feats)
    if hasattr(enc, "to_device"):
        enc = enc.to_device(ctranslate2.Device.cpu)
    arr = np.array(enc, dtype=np.float32)[0]                              # (1500 frames, 1280)
    n = max(1, min(arr.shape[0], int(round(len(audio) / SR / WIN_S * arr.shape[0]))))   # drop the padding frames
    return arr[:n].mean(axis=0)


def windows(audio: np.ndarray, turns: list[tuple[float, float]]) -> list[np.ndarray]:
    parts = [audio[int(s * SR): int(e * SR)] for s, e in turns if e - s >= MIN_TURN_S]
    if not parts:
        return []
    cat = np.concatenate(parts)
    step = int(WIN_S * SR)
    out = [cat[i: i + step] for i in range(0, len(cat), step)]
    return [w for w in out if len(w) >= MIN_TURN_S * SR]


def average(dists: list[dict[str, float]], weights: list[float]) -> dict[str, float]:
    tot = sum(weights)
    out: dict[str, float] = {}
    for d, w in zip(dists, weights):
        for k, p in d.items():
            out[k] = out.get(k, 0.0) + p * w / tot
    return out


def cmd_calls(a) -> int:
    from faster_whisper import decode_audio
    model, name = load_model(a.model, a.device, a.compute_type)
    calls = json.loads(a.manifest.read_text(encoding="utf-8"))["calls"]
    a.out.mkdir(parents=True, exist_ok=True)
    emb_rows: list[tuple[str, str, int, np.ndarray]] = []
    t_all = time.perf_counter()
    for c in calls:
        sp = a.speakers / f"{c['call_id']}.json"
        if not sp.is_file():
            print(f"{c['call_id']}: no speaker file, skipped", flush=True)
            continue
        turns = json.loads(sp.read_text(encoding="utf-8")).get("turns", [])
        p = Path(c["audio_path"])
        audio = decode_audio(str(p if p.is_absolute() else a.audio_root / p), sampling_rate=SR)
        t0 = time.perf_counter()
        speakers = {}
        for role in ("advisor", "customer"):
            ws = windows(audio, [(t["start_s"], t["end_s"]) for t in turns if t.get("role") == role])
            if not ws:
                continue
            dists = [detect(model, w) for w in ws]
            secs = [len(w) / SR for w in ws]
            speakers[role] = {"speech_s": round(sum(secs), 1), "chunks": len(ws),
                              "probs": {k: round(v, 5) for k, v in average(dists, secs).items() if v >= 1e-5}}
            if a.embed:
                emb_rows += [(c["call_id"], role, i, embed(model, w)) for i, w in enumerate(ws)]
        (a.out / f"{c['call_id']}.json").write_text(json.dumps(
            {"call_id": c["call_id"], "model": name, "window_s": WIN_S, "min_turn_s": MIN_TURN_S,
             "speakers": speakers, "elapsed_s": round(time.perf_counter() - t0, 2)}), encoding="utf-8")
        top = {r: max(s["probs"], key=s["probs"].get) for r, s in speakers.items()}
        print(f"{c['call_id']}: {top} ({time.perf_counter() - t0:.1f} s)", flush=True)
    if a.embed and emb_rows:
        np.savez_compressed(a.out / "_embeddings.npz", call_id=[r[0] for r in emb_rows], role=[r[1] for r in emb_rows],
                            window=[r[2] for r in emb_rows], emb=np.stack([r[3] for r in emb_rows]))
    print(f"{len(calls)} calls in {time.perf_counter() - t_all:.0f} s with {name}")
    return 0


def cmd_clips(a) -> int:
    """clips.json: [{"id", "path", "lang" (gold, Whisper code), "group" (e.g. speaker or sentence id), "set"}]"""
    from faster_whisper import decode_audio
    model, name = load_model(a.model, a.device, a.compute_type)
    clips = json.loads(a.clips.read_text(encoding="utf-8"))
    rows, embs = [], []
    for c in clips:
        audio = decode_audio(c["path"], sampling_rate=SR)[: int(WIN_S * SR)]
        d = detect(model, audio)
        pred = max(d, key=d.get)
        rows.append({**{k: c[k] for k in c if k != "path"}, "pred": pred, "p_pred": round(d[pred], 4),
                     "p_gold": round(d.get(c.get("lang", ""), 0.0), 4),
                     "top5": sorted(((k, round(v, 4)) for k, v in d.items()), key=lambda x: -x[1])[:5],
                     "duration_s": round(len(audio) / SR, 2)})
        if a.embed:
            embs.append(embed(model, audio))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"model": name, "clips": rows}, indent=1), encoding="utf-8")
    if a.embed:
        np.savez_compressed(a.out.with_suffix(".npz"), id=[r["id"] for r in rows], emb=np.stack(embs))
    by = {}
    for r in rows:
        by.setdefault((r.get("set"), r.get("lang")), []).append(r["pred"] == r.get("lang"))
    for k, v in sorted(by.items()):
        print(f"{k}: {sum(v)}/{len(v)} correct")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calls")
    c.add_argument("manifest", type=Path)
    c.add_argument("speakers", type=Path)
    c.add_argument("out", type=Path)
    c.add_argument("--audio-root", type=Path, default=REPO_ROOT)
    c.add_argument("--embed", action="store_true")
    k = sub.add_parser("clips")
    k.add_argument("clips", type=Path)
    k.add_argument("out", type=Path)
    k.add_argument("--embed", action="store_true")
    a = ap.parse_args(argv)
    return cmd_calls(a) if a.cmd == "calls" else cmd_clips(a)


if __name__ == "__main__":
    sys.exit(main())
