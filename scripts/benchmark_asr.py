"""Milestone 3: ASR bake-off on dev calls (+ SwissDial dialect robustness set). Label-free.

Reads only the dialogue splits, artifacts/manifests/inference.json (call id, audio path, variant) and
artifacts/manifests/reference_transcripts.json (script turns). It never opens evaluation.json; the
per-Stufe breakdown is scripts/report_asr_benchmark.py, run after the hypotheses exist.

Call selection (dev split only, holdout/test are never touched): twins are paired by their identical
reference script, so a "dialogue" = its clean + noisy recording. Default: 3 seeded dialogues from 3
different dev groups = 6 calls. --all-dev = every dev dialogue (GPU run).

Models: --models, else $ASR_MODELS (comma-separated), else DEFAULT_MODELS. Each is a faster-whisper
name (large-v3), a local CTranslate2 dir, or hf:<org>/<repo> for an HF-format fine-tune, converted
once with ct2-transformers-converter into artifacts/models/.

Per (model, call): normalised WER + CER vs the script, keyword recall (pipeline.asr_metrics, de OR gsw
variants of data/case/Stichwortliste.json), RTF, peak VRAM (nvidia-smi, CTranslate2 bypasses torch),
timestamp sanity. Decodes are cached exactly like pipeline/asr.py, so the winner's transcripts are reused.

    python scripts/benchmark_asr.py --models large-v3-turbo --limit-calls 1 --device cpu   # laptop smoke
    python scripts/benchmark_asr.py --all-dev --swissdial                                  # GPU
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import asr  # noqa: E402
from pipeline.asr_metrics import (cer, error_counts, keyword_recall, keyword_terms,  # noqa: E402
                                  timestamp_sanity, wer)
from pipeline.llm import load_env  # noqa: E402

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
INFERENCE_FILE = REPO_ROOT / "artifacts" / "manifests" / "inference.json"
REFERENCE_FILE = REPO_ROOT / "artifacts" / "manifests" / "reference_transcripts.json"
SWISSDIAL_FILE = REPO_ROOT / "artifacts" / "manifests" / "swissdial.json"
KEYWORDS_FILE = REPO_ROOT / "data" / "case" / "Stichwortliste.json"
MODELS_DIR = REPO_ROOT / "artifacts" / "models"
METRICS_DIR = REPO_ROOT / "artifacts" / "metrics"
DEFAULT_SEED = 20261010
DEFAULT_MODELS = [
    "large-v3",
    "large-v3-turbo",
    "hf:Flurin17/whisper-large-v3-turbo-swiss-german",   # cc-by-nc-4.0
    "hf:gcoli/whisper-large-v3-swiss-german-mit",        # MIT
]
TIE_RECALL = 0.01      # winner rule: keyword recall within 1 pp counts as a tie -> lower WER, then RTF


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def stable_key(seed: int, *parts: str) -> str:
    return hashlib.sha256(":".join([str(seed), *parts]).encode()).hexdigest()


# --------------------------------------------------------------------------- selection (label-free)

def dev_dialogues(splits: dict, inference: dict, reference: dict) -> list[dict]:
    """[{group_id, dialogue, call_ids}] for dev; twins share an identical reference script."""
    out = []
    for g in splits["splits"]["dev"]["groups"]:
        by_script = defaultdict(list)
        for cid in g["call_ids"]:
            h = hashlib.sha256(json.dumps(reference[cid], ensure_ascii=False, sort_keys=True).encode())
            by_script[h.hexdigest()[:12]].append(cid)
        for h, cids in sorted(by_script.items()):
            order = {"clean": 0, "noisy": 1}
            out.append({"group_id": g["group_id"], "dialogue": h,
                        "call_ids": sorted(cids, key=lambda c: (order.get(inference[c]["variant"], 2), c))})
    return out


def select_calls(splits: dict, inference: dict, reference: dict, n_dialogues: int = 3,
                 seed: int = DEFAULT_SEED, all_dev: bool = False) -> list[dict]:
    dialogues = dev_dialogues(splits, inference, reference)
    if not all_dev:
        groups = sorted({d["group_id"] for d in dialogues}, key=lambda g: stable_key(seed, g))[:n_dialogues]
        dialogues = [min((d for d in dialogues if d["group_id"] == g),
                         key=lambda d: stable_key(seed, d["dialogue"])) for g in groups]
    dev = set(splits["splits"]["dev"]["call_ids"])
    assert all(c in dev for d in dialogues for c in d["call_ids"]), "selection left the dev split"
    return dialogues


# --------------------------------------------------------------------------- models

def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", name)


def prepare_model(spec: str, quantization: str = "float16") -> str:
    """Model spec -> something pipeline.asr.resolve_model understands (converts hf: once)."""
    if not spec.startswith("hf:"):
        return spec
    repo = spec[3:]
    out = MODELS_DIR / f"{_safe(repo)}-ct2"
    if (out / "model.bin").is_file():
        return str(out)
    conv = shutil.which("ct2-transformers-converter") or str(Path(sys.executable).parent / "ct2-transformers-converter")
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    base = [conv, "--model", repo, "--output_dir", str(tmp), "--quantization", quantization]
    print(f"converting {repo} -> {out} ...", flush=True)
    r = subprocess.run(base + ["--copy_files", "tokenizer.json", "preprocessor_config.json"])
    if r.returncode != 0:      # some repos lack tokenizer.json; faster-whisper then falls back
        shutil.rmtree(tmp, ignore_errors=True)
        r = subprocess.run(base)
    if r.returncode != 0:
        raise RuntimeError(f"ct2 conversion failed for {repo}")
    tmp.replace(out)
    return str(out)


class VramPoller:
    """Peak GPU memory.used (MiB) above the pre-load baseline, via nvidia-smi. None without a GPU."""

    def __init__(self, interval: float = 0.2):
        self.interval, self.peak, self.baseline = interval, None, None
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    @staticmethod
    def read() -> int | None:
        if not shutil.which("nvidia-smi"):
            return None
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", "0"],
                           capture_output=True, text=True)
        try:
            return int(r.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            return None

    def start(self) -> "VramPoller":
        self.baseline = self.read()
        if self.baseline is None:
            return self
        self.peak = self.baseline

        def loop():
            while not self._stop.is_set():
                v = self.read()
                if v is not None:
                    self.peak = max(self.peak, v)
                self._stop.wait(self.interval)
        self._t = threading.Thread(target=loop, daemon=True)
        self._t.start()
        return self

    def stop(self) -> int | None:
        self._stop.set()
        if self._t:
            self._t.join()
        return None if self.peak is None else self.peak - self.baseline


# --------------------------------------------------------------------------- decoding

RTF_NOT_MEASURED = "not measured in this config"


def warm_up(model) -> int:
    """Decode 5 s of silence so the first call's RTF excludes kernel set-up. faster-whisper returns a lazy
    generator, so it must be consumed; VAD is off because it would drop silence and skip the decode."""
    import numpy as np
    segments, _ = model.transcribe(np.zeros(16000 * 5, dtype="float32"), language="de", beam_size=1,
                                   vad_filter=False)
    return len(list(segments))


def decode_cached(model, asr_model: str, audio: Path, timing: dict,
                  force: bool = False) -> tuple[dict, float | None, bool]:
    """(raw, elapsed_s, from_cache). Same cache files as pipeline/asr.py. A cached hypothesis is always
    reused; its elapsed time only if it was measured with this device + compute_type + host, else None."""
    cp = asr.CACHE_DIR / f"{asr.cache_key(asr._sha256(audio), asr_model)}.json"
    if cp.is_file() and not force:
        c = _load(cp)
        return c["raw"], asr.cached_elapsed(c, timing), True
    m = model()                      # load + warm-up stay outside the timed decode
    t0 = time.perf_counter()
    raw = asr.decode(m, audio)
    elapsed = time.perf_counter() - t0
    asr.write_cache(cp, asr_model, raw, elapsed, timing)
    return raw, elapsed, False


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def _hyp(raw: dict) -> str:
    return " ".join(s["text"] for s in raw["segments"])


def _pooled(rows: list[dict], key: str) -> float | None:
    e, n = sum(r[key][0] for r in rows), sum(r[key][1] for r in rows)
    return round(e / n, 4) if n else None


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {}
    kp, kt = sum(r["keywords"]["presence_hits"] for r in rows), sum(r["keywords"]["presence_total"] for r in rows)
    op, ot = sum(r["keywords"]["occurrence_hits"] for r in rows), sum(r["keywords"]["occurrence_total"] for r in rows)
    timed = [r for r in rows if r["elapsed_s"] is not None]
    return {
        "n": len(rows),
        "wer": _pooled(rows, "word_errors"), "cer": _pooled(rows, "char_errors"),
        "keyword_recall": round(kp / kt, 4) if kt else None, "keyword_presence": [kp, kt],
        "keyword_occurrence_recall": round(op / ot, 4) if ot else None,
        "rtf": round(sum(r["elapsed_s"] for r in timed) / sum(r["duration_s"] for r in timed), 4) if timed else None,
        "rtf_n": len(timed),
        **({} if timed else {"rtf_note": RTF_NOT_MEASURED}),
        "timestamps_ok_frac": round(sum(r["timestamps"]["ok"] for r in rows) / len(rows), 4),
    }


def pick_winner(models: dict, vram_budget_mb: int | None) -> dict:
    cands, excluded = [], {}
    for name, m in models.items():
        s = m.get("summary") or {}
        if m.get("error") or s.get("keyword_recall") is None:
            continue
        if vram_budget_mb:
            # Under a budget, only a model that was loaded and measured here can be shown to fit.
            vram = m.get("peak_vram_mb") if m.get("vram_measured") else None
            if not vram:
                excluded[name] = "VRAM not measured (model not loaded in this run, or no GPU)"
                continue
            if vram > vram_budget_mb:
                excluded[name] = f"peak VRAM {vram} MiB > {vram_budget_mb} MiB"
                continue
        cands.append((name, s))
    if not cands:
        return {"model": None, "rule": "no eligible model", "excluded": excluded}
    best_recall = max(s["keyword_recall"] for _, s in cands)
    tied = [(n, s) for n, s in cands if s["keyword_recall"] >= best_recall - TIE_RECALL]
    tied.sort(key=lambda x: (x[1]["wer"] if x[1]["wer"] is not None else 9,
                             x[1]["rtf"] if x[1]["rtf"] is not None else float("inf")))
    return {"model": tied[0][0], "tied_on_recall": [n for n, _ in tied], "excluded": excluded,
            "rule": f"max keyword recall; within {TIE_RECALL:.0%} -> lowest WER, then lowest RTF"
                    + (f"; peak VRAM <= {vram_budget_mb} MiB" if vram_budget_mb else "")}


# --------------------------------------------------------------------------- main

def run(args) -> dict:
    load_env()
    specs = args.models or [m.strip() for m in os.environ.get("ASR_MODELS", "").split(",") if m.strip()] or DEFAULT_MODELS
    splits, reference = _load(SPLITS_FILE), _load(REFERENCE_FILE)["calls"]
    inference = {c["call_id"]: c for c in _load(INFERENCE_FILE)["calls"]}
    terms = keyword_terms(_load(KEYWORDS_FILE))
    dialogues = select_calls(splits, inference, reference, args.dialogues, args.seed, args.all_dev)
    call_ids = [c for d in dialogues for c in d["call_ids"]][:args.limit_calls or None]
    swiss = _load(SWISSDIAL_FILE)["utterances"] if args.swissdial else []
    if args.swissdial_per_dialect:
        keep = sorted({u["sentence_id"] for u in swiss})[:args.swissdial_per_dialect]
        swiss = [u for u in swiss if u["sentence_id"] in keep]
    device = args.device or asr.default_device()[0]
    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")
    timing = asr.timing_config(device, compute_type)
    print(f"device={device}/{compute_type} host={timing['host']}  calls={call_ids}  swissdial={len(swiss)} utts  "
          f"models={specs}", flush=True)

    result = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": args.seed,
              **timing, "decode": asr.DECODE,
              "asr_version": asr.ASR_VERSION, "selection": {"all_dev": args.all_dev, "dialogues": dialogues,
                                                             "call_ids": call_ids},
              "keywords_source": str(KEYWORDS_FILE.relative_to(REPO_ROOT)), "models": {}}
    for spec in specs:
        entry: dict = {"spec": spec}
        result["models"][spec] = entry
        try:
            model_dir, asr_model = asr.resolve_model(prepare_model(spec))
        except Exception as exc:
            entry["error"] = f"prepare: {type(exc).__name__}: {exc}"
            print(f"[{spec}] {entry['error']}", flush=True)
            continue
        entry["asr_model"] = asr_model
        vram = VramPoller().start()
        holder: dict = {}

        def model():   # lazy: a fully cached model is never loaded
            if "m" not in holder:
                t0 = time.perf_counter()
                holder["m"] = asr.load_model(model_dir, device, compute_type)
                entry["load_s"] = round(time.perf_counter() - t0, 2)
                warm_up(holder["m"])
            return holder["m"]

        rows, srows = [], []
        try:
            for cid in call_ids:
                audio = REPO_ROOT / inference[cid]["audio_path"]
                raw, elapsed, cached = decode_cached(model, asr_model, audio, timing, args.force)
                ref = " ".join(t["text"] for t in reference[cid])
                hyp = _hyp(raw)
                dur = inference[cid]["duration_s"]
                rows.append({
                    "call_id": cid, "variant": inference[cid]["variant"], "duration_s": dur,
                    "elapsed_s": _r(elapsed), "rtf": _r(None if elapsed is None else elapsed / dur, 4),
                    **({} if elapsed is not None else {"rtf_note": RTF_NOT_MEASURED}), "cached": cached,
                    "wer": wer(ref, hyp), "cer": cer(ref, hyp),
                    "word_errors": list(error_counts(ref, hyp, "word")),
                    "char_errors": list(error_counts(ref, hyp, "char")),
                    "keywords": keyword_recall(ref, hyp, terms),
                    "timestamps": timestamp_sanity(raw["segments"], dur),
                    "language": raw.get("language"), "hypothesis": hyp,
                })
                r = rows[-1]
                print(f"[{spec}] {cid} {r['variant']:5s} WER {r['wer']:.3f} CER {r['cer']:.3f} "
                      f"kw {r['keywords']['presence_hits']}/{r['keywords']['presence_total']} "
                      f"RTF {RTF_NOT_MEASURED if r['rtf'] is None else format(r['rtf'], '.3f')}"
                      f"{' (cached)' if cached else ''} ts_ok={r['timestamps']['ok']}", flush=True)
            for u in swiss:
                audio = REPO_ROOT / u["audio_path"]
                raw, elapsed, cached = decode_cached(model, asr_model, audio, timing, args.force)
                hyp = _hyp(raw)
                srows.append({"utt_id": u["utt_id"], "dialect": u["dialect"], "elapsed_s": _r(elapsed),
                              "cached": cached, "hypothesis": hyp,
                              "de_word_errors": list(error_counts(u["ref_de"], hyp, "word")),
                              "de_char_errors": list(error_counts(u["ref_de"], hyp, "char")),
                              "gsw_word_errors": list(error_counts(u["ref_gsw"], hyp, "word")),
                              "gsw_char_errors": list(error_counts(u["ref_gsw"], hyp, "char"))})
        except Exception as exc:
            entry["error"] = f"decode: {type(exc).__name__}: {exc}"
            print(f"[{spec}] {entry['error']}", flush=True)
        finally:
            entry["peak_vram_mb"] = vram.stop()
            entry["vram_measured"] = "m" in holder and entry["peak_vram_mb"] is not None
            holder.clear()
            asr.load_model.cache_clear()

        entry["calls"] = rows
        entry["summary"] = summarise(rows)
        entry["by_variant"] = {v: summarise([r for r in rows if r["variant"] == v])
                               for v in sorted({r["variant"] for r in rows})}
        if srows:
            entry["swissdial"] = {
                d: {"n": len(rs),
                    "wer_de": _pooled(rs, "de_word_errors"), "cer_de": _pooled(rs, "de_char_errors"),
                    "wer_gsw": _pooled(rs, "gsw_word_errors"), "cer_gsw": _pooled(rs, "gsw_char_errors")}
                for d in sorted({r["dialect"] for r in srows})
                for rs in [[r for r in srows if r["dialect"] == d]]}
            entry["swissdial_utterances"] = srows

    result["winner"] = pick_winner(result["models"], args.vram_budget_mb)
    return result


def markdown(result: dict) -> str:
    lines = ["| model | n | WER | CER | kw recall | kw occ. | RTF | peak VRAM MiB | ts ok | clean WER | noisy WER |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, p=3: "–" if v is None else (f"{v:.{p}f}" if isinstance(v, float) else str(v))  # noqa: E731
    for name, m in result["models"].items():
        if m.get("error") and not m.get("calls"):
            lines.append(f"| {name} | error: {m['error']} |||||||||| ")
            continue
        s, bv = m["summary"], m.get("by_variant", {})
        kw = f"{f(s.get('keyword_recall'))} ({s['keyword_presence'][0]}/{s['keyword_presence'][1]})" if s else "–"
        lines.append(f"| {name} | {s.get('n', 0)} | {f(s.get('wer'))} | {f(s.get('cer'))} | {kw} | "
                     f"{f(s.get('keyword_occurrence_recall'))} | {f(s.get('rtf'))} | {f(m.get('peak_vram_mb'))} | "
                     f"{f(s.get('timestamps_ok_frac'), 2)} | {f(bv.get('clean', {}).get('wer'))} | "
                     f"{f(bv.get('noisy', {}).get('wer'))} |")
    sd = [(n, m["swissdial"]) for n, m in result["models"].items() if m.get("swissdial")]
    if sd:
        dialects = sorted({d for _, s in sd for d in s})
        lines += ["", "SwissDial WER vs Standard German (de) / vs dialect transcript (gsw):", "",
                  "| model | " + " | ".join(dialects) + " |", "|---|" + "---|" * len(dialects)]
        for n, s in sd:
            lines.append(f"| {n} | " + " | ".join(f"{f(s[d]['wer_de'], 2)} / {f(s[d]['wer_gsw'], 2)}"
                                                    if d in s else "–" for d in dialects) + " |")
    w = result["winner"]
    lines += ["", f"winner: {w['model']}  ({w['rule']})"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=lambda s: [m.strip() for m in s.split(",") if m.strip()])
    ap.add_argument("--dialogues", type=int, default=3, help="seeded dev dialogues (x2 calls)")
    ap.add_argument("--all-dev", action="store_true", help="every dev dialogue")
    ap.add_argument("--limit-calls", type=int, help="first N selected calls only (smoke runs)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--swissdial", action="store_true", help="also decode artifacts/manifests/swissdial.json")
    ap.add_argument("--swissdial-per-dialect", type=int, help="first N sampled sentences per dialect")
    ap.add_argument("--device", choices=["cpu", "cuda"])
    ap.add_argument("--compute-type")
    ap.add_argument("--vram-budget-mb", type=int, help="exclude models above this peak VRAM from the winner")
    ap.add_argument("--force", action="store_true", help="ignore cached decodes")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    result = run(args)
    out = args.out or METRICS_DIR / f"asr_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n" + markdown(result) + f"\n\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
