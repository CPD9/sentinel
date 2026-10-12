"""Summary of a run_test_set.sh run: decisions, timing and (only if labels are given) quality.

    python scripts/test_set_summary.py <out_dir> [--pod-asr "<pod_asr_timing line>"] [--labels labels.json|.csv]
                                       [--total-s S] [--label NAME] [--format wav|flac]

Writes <out_dir>/timing_summary.json and prints a short report. Labels are read here, after the predictions exist,
never by the pipeline: a JSON {"<original file name>": "alarm|review|no_alert"} or a CSV with columns file,label.
Labels are joined by source file: the original name (e.g. TEST-02.mp3) through out/source_files.json to the
converted WAV the pipeline saw (TEST-02.wav) and its neutral call id; failing that, by file stem.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.evaluate import metric_block  # noqa: E402

LABELS = {"alarm", "review", "no_alert"}


def read_labels(p: Path) -> dict[str, str]:
    if p.suffix.lower() == ".csv":
        with p.open(newline="", encoding="utf-8") as f:
            rows = {r["file"].strip(): r["label"].strip() for r in csv.DictReader(f)}
    else:
        rows = json.loads(p.read_text(encoding="utf-8"))
    bad = {k: v for k, v in rows.items() if v not in LABELS}
    if bad:
        raise SystemExit(f"labels must be one of {sorted(LABELS)}: {list(bad.items())[:3]}")
    return rows


def parse_pod(line: str | None) -> dict | None:
    if not line:
        return None
    kv = dict(t.split("=", 1) for t in line.split()[1:] if "=" in t)
    return {k: (float(v) if k.endswith("_s") else v) for k, v in kv.items()}


def summarize(out: Path, pod: dict | None, labels: dict[str, str] | None, total_s: float | None,
              label: str | None, fmt: str | None) -> dict:
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    tim = json.loads((out / "timings.json").read_text(encoding="utf-8")) if (out / "timings.json").is_file() else {}
    idm = json.loads((out / "id_map.json").read_text(encoding="utf-8"))["map"] if (out / "id_map.json").is_file() else {}
    calls = res["calls"]
    counts = {k: sum(c["decision"] == k for c in calls) for k in ("alarm", "review", "no_alert")}
    errs = sum(len(c.get("stage_errors") or []) for c in calls)
    body = {
        "label": label, "files": len(calls), "format": fmt, "workers": tim.get("workers"), "decisions": counts,
        "stage_errors": errs, "pod_asr": pod, "pipeline_wall_s": tim.get("wall_s"), "total_s": total_s,
        "per_call_s": tim.get("per_call_s"), "throughput_calls_per_min": tim.get("throughput_calls_per_min"),
        "stages": tim.get("stages"),
    }
    try:
        import soundfile as sf
        body["audio_s_total"] = round(sum(sf.info(str(p)).duration for p in _wavs(out, idm)), 1)
    except Exception:
        pass
    if labels:
        by_id = join_labels(labels, idm, _source_files(out))
        ids = [c["call_id"] for c in calls if c["call_id"] in by_id]
        if ids:
            dec = {c["call_id"]: c["decision"] for c in calls}
            body["quality"] = metric_block([by_id[i] for i in ids], [dec[i] for i in ids])
            body["quality"]["unlabelled"] = len(calls) - len(ids)
    (out / "timing_summary.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
    return body


def _source_files(out: Path) -> dict:
    f = out / "source_files.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def join_labels(labels: dict[str, str], idm: dict[str, str], sources: dict) -> dict[str, str]:
    """call id -> gold label. A label key is an original file name (or a stem): original name -> stem via
    source_files.json, else the key's own stem; stem -> the processed WAV (<stem>.wav) -> neutral call id."""
    by_stem = {Path(wav).stem: cid for wav, cid in idm.items()}
    orig_to_stem = {v["file"]: stem for stem, v in sources.items()}
    out = {}
    for key, lab in labels.items():
        stem = orig_to_stem.get(key) or Path(key).stem
        if stem in by_stem:
            out[by_stem[stem]] = lab
    return out


def _wavs(out: Path, idm: dict) -> list[Path]:
    src = out / "source_folder.txt"
    if not src.is_file():
        return []
    folder = Path(src.read_text().strip())
    return [folder / n for n in idm] if idm else sorted(folder.glob("*.wav"))


def report(b: dict) -> str:
    L = [f"{b['files']} calls · decisions {b['decisions']} · stage errors {b['stage_errors']}"]
    if b.get("pod_asr"):
        p = b["pod_asr"]
        L.append(f"Pod ASR ({p.get('format')}, {p.get('size')}): upload {p['upload_s']:.0f} s, GPU decode "
                 f"{p['decode_s']:.0f} s, download {p['download_s']:.0f} s, total {p['total_s']:.0f} s")
    if b.get("pipeline_wall_s"):
        pc = b.get("per_call_s") or {}
        L.append(f"pipeline ({b['workers']} workers): {b['pipeline_wall_s']:.0f} s wall, "
                 f"{b.get('throughput_calls_per_min')} calls/min, per call median {pc.get('median')} s")
    if b.get("total_s"):
        L.append(f"TOTAL end to end: {b['total_s']:.0f} s ({b['total_s'] / 60:.1f} min)")
    q = b.get("quality")
    if q:
        e, s = q["escalation"], q["strict_alarm"]
        L.append(f"quality on {q['n']} labelled calls: escalation P {e['precision']} R {e['recall']} "
                 f"(fp {e['fp']}, fn {e['fn']}); strict alarm P {s['precision']} R {s['recall']}; "
                 f"3-class macro F1 {q['three_class'].get('macro_f1')}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--pod-asr")
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--total-s", type=float)
    ap.add_argument("--label")
    ap.add_argument("--format")
    a = ap.parse_args(argv)
    b = summarize(a.out, parse_pod(a.pod_asr), read_labels(a.labels) if a.labels else None, a.total_s, a.label,
                  a.format)
    print(report(b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
