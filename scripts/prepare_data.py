"""Milestone 1: inspect the case data and build leakage-safe manifests and dialogue splits.

Reads (never writes) the original data under data/:
  data/case/    public 70 % package (Audio/, Transkript/, Skript_mit_Sollbewertung/)
  data/test30/  organizers' 30 % package -> locked "test" split, never tuned on

Writes under artifacts/:
  audio/call_XXX.wav               neutral copies (APFS clones on macOS) of every recording
  manifests/inference.json         call_id, audio path, variant, duration. No labels, no names.
  manifests/evaluation.json        call_id -> original file, dialogue, Stufe, label, reasoning, passages
  manifests/data_report.json       inspection findings, README cross-check, split stratification
  splits/dialogue_splits.json      dev / holdout / test as call_id groups (label-free)

Usage: python scripts/prepare_data.py [--data-dir data] [--out artifacts] [--seed N]
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 20261009
HOLDOUT_FRACTION = 0.3

# (source name, sub-folder of data dir, split policy, README claim: (recordings, dialogues))
SOURCES = [
    ("case", "case", "pool", (42, 21)),
    ("test30", "test30", "test", (20, 11)),
]

AUDIO_RE = re.compile(r"^Stufe(?P<stufe>[123])_(?P<dlg>[CDM]\d{2})(?:-(?P<take>K[1-4]))?\.wav$")
SCRIPT_RE = re.compile(r"^Stufe(?P<stufe>[123])_(?P<dlg>[CDM]\d{2})\.txt$")
TAKE_VARIANT = {"K1": "clean", "K3": "clean", "K2": "noisy", "K4": "noisy", None: "unspecified"}
LABELS = {"alarm", "no_alert", "review"}
SPEAKERS = {"Beratung": "advisor", "B": "advisor", "Kundin": "customer", "Kunde": "customer",
            "K": "customer"}

TURN_DOT_RE = re.compile(r"^(T\d{3}) · (\S+)$")            # C/D format: "T001 · Beratung" + text lines
TURN_INLINE_RE = re.compile(r"^(T\d{3}) ([A-Z]): (.*)$")    # M format:   "T001 B: text"
HEADER_KEY_RE = re.compile(r"^([A-ZÄÖÜ][\wÄÖÜäöüß ]{1,40}): ?(.*)$")
PASSAGE_RE = re.compile(r"^\s+(T\d{3}) ([A-Z]): «(.*)»\s*(?:\((.*)\))?\s*$")
PREFIX_RE = re.compile(r"^Prüfpräfix bis (T\d{3}); Belege: (.*)$")


# --------------------------------------------------------------------------- parsing

def parse_turns(lines: list[str]) -> list[dict]:
    turns: list[dict] = []
    for line in lines:
        line = line.rstrip()
        if m := TURN_INLINE_RE.match(line):
            turns.append({"turn_id": m[1], "speaker_raw": m[2], "text": m[3].strip()})
        elif m := TURN_DOT_RE.match(line):
            turns.append({"turn_id": m[1], "speaker_raw": m[2], "text": ""})
        elif line.strip() and turns:
            turns[-1]["text"] = (turns[-1]["text"] + " " + line.strip()).strip()
    for t in turns:
        t["speaker"] = SPEAKERS.get(t["speaker_raw"], "unknown")
    return turns


def split_header_body(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if TURN_DOT_RE.match(line) or TURN_INLINE_RE.match(line):
            return lines[:i], lines[i:]
    return lines, []


def parse_assessment(path: Path) -> dict:
    header, body = split_header_body(path.read_text(encoding="utf-8"))
    title_line = header[0].strip()
    dlg_id, _, title = title_line.partition(" · ")
    fields: dict[str, str] = {}
    description: list[str] = []
    passages: list[dict] = []
    in_passages = False
    for line in header[1:]:
        if not line.strip():
            in_passages = False
            continue
        if in_passages and (m := PASSAGE_RE.match(line)):
            passages.append({"turn_id": m[1], "speaker_raw": m[2], "quote": m[3], "note": m[4]})
            continue
        in_passages = False
        if pm := PREFIX_RE.match(line.strip()):
            fields["Prüfpräfix"] = pm[1]
            fields["Belege"] = pm[2]
            continue
        if (m := HEADER_KEY_RE.match(line)) and not fields.get("_script_header"):
            key, value = m[1], m[2].strip()
            if key == "Belegstellen laut Skript":
                in_passages = True
                continue
            fields[key] = value
        elif line.startswith(dlg_id + " ") and not line.startswith(title_line):
            # M format repeats "M07 <title>" as the start of the embedded script header
            fields["_script_header"] = line.strip()
        elif not fields:
            description.append(line.strip())
    fields.pop("_script_header", None)
    turns = parse_turns(body)
    evidence_ids = [t.strip() for t in fields.get("Belege", "").split(",") if t.strip()]
    if not evidence_ids:
        evidence_ids = [p["turn_id"] for p in passages]
    return {
        "dialogue_id": dlg_id.strip(),
        "title": title.strip(),
        "description": " ".join(description) or None,
        "fields": fields,
        "passages": passages,
        "evidence_turn_ids": evidence_ids,
        "turns": turns,
    }


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        frames, rate = w.getnframes(), w.getframerate()
        return {"duration_s": round(frames / rate, 3), "sample_rate": rate,
                "channels": w.getnchannels(), "sample_width_bytes": w.getsampwidth()}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_key(seed: int, *parts: str) -> str:
    return hashlib.sha256(":".join([str(seed), *parts]).encode()).hexdigest()


def clone_file(src: Path, dst: Path) -> None:
    """Copy src to dst. On macOS use an APFS clone (no extra disk space, independent file)."""
    if dst.exists() and dst.stat().st_size == src.stat().st_size and sha256_file(dst) == sha256_file(src):
        return
    tmp = dst.with_suffix(".tmp")
    if sys.platform == "darwin":
        r = subprocess.run(["cp", "-c", str(src), str(tmp)], capture_output=True)
        if r.returncode != 0:
            shutil.copyfile(src, tmp)
    else:
        shutil.copyfile(src, tmp)
    os.chmod(tmp, 0o644)
    os.replace(tmp, dst)


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


# --------------------------------------------------------------------------- inspection

def inspect_source(name: str, root: Path, claim: tuple[int, int], issues: list[str]) -> dict:
    audio = sorted((root / "Audio").glob("*.wav"))
    scripts = sorted((root / "Skript_mit_Sollbewertung").glob("*.txt"))
    transcripts = sorted((root / "Transkript").glob("*.txt"))

    dialogues: dict[str, dict] = {}
    for sp in scripts:
        m = SCRIPT_RE.match(sp.name)
        if not m:
            issues.append(f"{name}: unexpected assessment file name {sp.name}")
            continue
        a = parse_assessment(sp)
        if a["dialogue_id"] != m["dlg"]:
            issues.append(f"{name}: {sp.name} header id {a['dialogue_id']} != file name id {m['dlg']}")
        label = a["fields"].get("Bearbeitung")
        if label not in LABELS:
            issues.append(f"{name}: {sp.name} has unknown Bearbeitung {label!r}")
        tp = root / "Transkript" / sp.name
        transcript_turns = parse_turns(split_header_body(tp.read_text(encoding="utf-8"))[1]) if tp.exists() else []
        if not tp.exists():
            issues.append(f"{name}: no transcript for {sp.name}")
        elif [(t["turn_id"], t["speaker_raw"], t["text"]) for t in transcript_turns] != \
                [(t["turn_id"], t["speaker_raw"], t["text"]) for t in a["turns"]]:
            issues.append(f"{name}: dialogue in Transkript/{sp.name} differs from Skript_mit_Sollbewertung")
        turn_by_id = {t["turn_id"]: t for t in a["turns"]}
        unknown_speakers = sorted({t["speaker_raw"] for t in a["turns"] if t["speaker"] == "unknown"})
        if unknown_speakers:
            issues.append(f"{name}: {sp.name} has unmapped speaker labels {unknown_speakers}")
        key_passages = []
        quotes = {p["turn_id"]: p for p in a["passages"]}
        for tid in a["evidence_turn_ids"]:
            t = turn_by_id.get(tid)
            if t is None:
                issues.append(f"{name}: {sp.name} cites evidence turn {tid} that is not in the script")
                continue
            p = quotes.get(tid, {})
            if p and p["quote"] not in t["text"]:
                issues.append(f"{name}: {sp.name} quoted passage for {tid} is not verbatim in the script turn")
            key_passages.append({"turn_id": tid, "speaker": t["speaker"], "text": t["text"],
                                 "quote": p.get("quote"), "note": p.get("note")})
        f = a["fields"]
        dialogues[m["dlg"]] = {
            "dialogue_id": m["dlg"],
            "source": name,
            "stufe": int(m["stufe"]),
            "recording": "human" if m["dlg"].startswith("M") else "synthetic",
            "title": a["title"],
            "description": a["description"] or f.get("Zusammenfassung"),
            "label": label,
            "reasoning": f.get("Begründung"),
            "test_target": f.get("Testziel"),
            "task": f.get("Aufgabe"),
            "event": f.get("Ereignis"),
            "outcome": f.get("Ergebnis"),
            "open_question": f.get("Offen"),
            "check_prefix_until": f.get("Prüfpräfix"),
            "evidence_turn_ids": a["evidence_turn_ids"],
            "key_passages": key_passages,
            "n_turns": len(a["turns"]),
            "transcript_path": rel(tp),
            "assessment_path": rel(sp),
            "header_fields": f,
            "call_ids": [],
        }
    for tp in transcripts:
        if not (root / "Skript_mit_Sollbewertung" / tp.name).exists():
            issues.append(f"{name}: transcript {tp.name} has no assessment")

    recordings = []
    for ap in audio:
        m = AUDIO_RE.match(ap.name)
        if not m:
            issues.append(f"{name}: unexpected audio file name {ap.name}")
            continue
        dlg = m["dlg"]
        if dlg not in dialogues:
            issues.append(f"{name}: audio {ap.name} has no assessment/transcript")
            continue
        if int(m["stufe"]) != dialogues[dlg]["stufe"]:
            issues.append(f"{name}: audio {ap.name} Stufe differs from its script")
        info = wav_info(ap)
        if (info["channels"], info["sample_rate"], info["sample_width_bytes"]) != (1, 16000, 2):
            issues.append(f"{name}: {ap.name} is not mono/16 kHz/16-bit: {info}")
        recordings.append({"source": name, "path": ap, "dialogue_id": dlg, "stufe": int(m["stufe"]),
                           "take": m["take"], "variant": TAKE_VARIANT[m["take"]], **info})

    # each synthetic dialogue: exactly one clean + one noisy; human (M) recordings: exactly one take
    takes = defaultdict(list)
    for r in recordings:
        takes[r["dialogue_id"]].append(r)
    for dlg, d in dialogues.items():
        got = sorted(r["variant"] for r in takes.get(dlg, []))
        want = ["unspecified"] if d["recording"] == "human" else ["clean", "noisy"]
        if got != want:
            issues.append(f"{name}: dialogue {dlg} has variants {got}, expected {want}")
        if d["recording"] == "synthetic":
            ks = sorted(r["take"] for r in takes.get(dlg, []))
            expected_ks = ["K1", "K2"] if dlg.startswith("D") else ["K3", "K4"]
            if ks != expected_ks:
                issues.append(f"{name}: dialogue {dlg} takes {ks}, expected {expected_ks}")

    # Stufe2 context pairs ("twins"): same title, consecutive numbers
    by_title = defaultdict(list)
    for d in dialogues.values():
        by_title[(d["stufe"], d["title"])].append(d["dialogue_id"])
    for (stufe, title), ids in by_title.items():
        ids.sort()
        if stufe == 2 and len(ids) != 2:
            issues.append(f"{name}: Stufe2 '{title}' has {len(ids)} dialogues {ids}, expected a pair")
        if stufe != 2 and len(ids) != 1:
            issues.append(f"{name}: Stufe{stufe} dialogues {ids} share the title '{title}'")
        if len(ids) == 2:
            a, b = (int(i[1:]) for i in ids)
            if b != a + 1 or a % 2 == 0:
                issues.append(f"{name}: pair {ids} is not numbered (odd, odd+1)")
        for i in ids:
            dialogues[i]["twin_dialogue_ids"] = [j for j in ids if j != i]

    readme_check = {
        "readme_recordings": claim[0], "found_recordings": len(audio),
        "readme_dialogues": claim[1], "found_dialogues": len(dialogues),
        "found_transcripts": len(transcripts), "found_assessments": len(scripts),
    }
    if len(audio) != claim[0] or len(dialogues) != claim[1] or len(transcripts) != claim[1]:
        issues.append(f"{name}: counts differ from README: {readme_check}")
    return {"dialogues": dialogues, "recordings": recordings, "readme_check": readme_check}


# --------------------------------------------------------------------------- splitting

def make_units(dialogues: dict[str, dict], seed: int) -> list[dict]:
    """A unit is a set of dialogues that must stay together: a Stufe2 twin pair or a single dialogue."""
    seen, units = set(), []
    for dlg in sorted(dialogues):
        if dlg in seen:
            continue
        members = sorted([dlg, *dialogues[dlg].get("twin_dialogue_ids", [])])
        seen.update(members)
        ds = [dialogues[m] for m in members]
        units.append({
            "dialogue_ids": members,
            "source": ds[0]["source"],
            "stufe": ds[0]["stufe"],
            "labels": sorted(d["label"] for d in ds),
            "targets": sorted({d["test_target"] for d in ds if d["test_target"]}),
            "sort_key": stable_key(seed, "unit", *members),
        })
    units.sort(key=lambda u: u["sort_key"])
    for i, u in enumerate(units, 1):
        u["group_id"] = f"g{i:02d}"
    return units


def assign_splits(units: list[dict], seed: int, frac: float, notes: list[str]) -> dict:
    """Stratify by (Stufe, label signature): each stratum sends round(frac * n) units to holdout.

    The data is too small to also stratify on test target (numbers / trade / access / ...), so among
    all allowed holdout choices we take the one where dev still covers every test target and holdout
    covers as many as possible; ties are broken by a seeded hash, so the result is deterministic.
    """
    strata = defaultdict(list)
    for u in units:
        if u["source"] == "test30":
            u["split"] = "test"
            continue
        strata[(u["stufe"], "+".join(u["labels"]))].append(u)
    keys = sorted(strata)
    n_hold = {}
    for key in keys:
        n = len(strata[key])
        k = math.floor(frac * n + 0.5)
        n_hold[key] = min(max(k, 1), n - 1) if n >= 2 else 0
        if n < 2:
            notes.append(f"stratum Stufe{key[0]} [{key[1]}] has a single unit; kept in dev, "
                         f"so holdout has no example of it")
    pool = [u for key in keys for u in strata[key]]
    all_targets = {t for u in pool for t in u["targets"] if t}
    options = [list(itertools.combinations(sorted(strata[k], key=lambda u: u["group_id"]), n_hold[k]))
               for k in keys]
    best, best_score = None, None
    for choice in itertools.product(*options):
        hold_ids = {u["group_id"] for combo in choice for u in combo}
        hold_t = {t for u in pool if u["group_id"] in hold_ids for t in u["targets"]}
        dev_t = {t for u in pool if u["group_id"] not in hold_ids for t in u["targets"]}
        score = (dev_t == all_targets, len(hold_t), stable_key(seed, "holdout", *sorted(hold_ids)))
        if best_score is None or score > best_score:
            best, best_score = hold_ids, score
    for u in pool:
        u["split"] = "holdout" if u["group_id"] in best else "dev"
    stratum_report = []
    for key in keys:
        members = strata[key]
        stratum_report.append({
            "stufe": key[0], "labels": key[1], "units": len(members),
            "holdout_units": n_hold[key], "dev_units": len(members) - n_hold[key],
            "holdout_dialogues": sorted(d for u in members if u["split"] == "holdout" for d in u["dialogue_ids"]),
            "dev_dialogues": sorted(d for u in members if u["split"] == "dev" for d in u["dialogue_ids"]),
        })
    return {"strata": stratum_report}


# --------------------------------------------------------------------------- main

def build(data_dir: Path, out_dir: Path, seed: int = DEFAULT_SEED, frac: float = HOLDOUT_FRACTION) -> dict:
    data_dir, out_dir = data_dir.resolve(), out_dir.resolve()
    if out_dir == data_dir or data_dir in out_dir.parents:
        raise SystemExit(f"refusing to write inside the data directory: {out_dir}")

    issues: list[str] = []
    notes: list[str] = []
    dialogues: dict[str, dict] = {}
    recordings: list[dict] = []
    readme_checks = {}
    for name, sub, _policy, claim in SOURCES:
        root = data_dir / sub
        if not root.is_dir():
            raise SystemExit(f"missing data source {root}")
        res = inspect_source(name, root, claim, issues)
        clash = set(res["dialogues"]) & set(dialogues)
        if clash:
            raise SystemExit(f"dialogue ids appear in more than one source: {sorted(clash)}")
        dialogues.update(res["dialogues"])
        recordings.extend(res["recordings"])
        readme_checks[name] = res["readme_check"]

    # neutral call ids: ordered by a seeded hash, so numbering carries no Stufe / file-name order
    recordings.sort(key=lambda r: stable_key(seed, "call", r["source"], r["path"].name))
    for i, r in enumerate(recordings, 1):
        r["call_id"] = f"call_{i:03d}"
        dialogues[r["dialogue_id"]]["call_ids"].append(r["call_id"])
    for d in dialogues.values():
        d["call_ids"].sort()

    units = make_units(dialogues, seed)
    split_stats = assign_splits(units, seed, frac, notes)
    for u in units:
        for dlg in u["dialogue_ids"]:
            dialogues[dlg]["split"] = u["split"]
            dialogues[dlg]["group_id"] = u["group_id"]

    audio_dir = out_dir / "audio"
    man_dir = out_dir / "manifests"
    split_dir = out_dir / "splits"
    for d in (audio_dir, man_dir, split_dir):
        d.mkdir(parents=True, exist_ok=True)
    wanted = {f"{r['call_id']}.wav" for r in recordings}
    for stale in audio_dir.glob("*.wav"):
        if stale.name not in wanted:
            stale.unlink()  # only our own neutral copies from an earlier run
    for r in recordings:
        clone_file(r["path"], audio_dir / f"{r['call_id']}.wav")

    inference = {
        "schema_version": 1,
        "calls": [
            {"call_id": r["call_id"], "audio_path": rel(audio_dir / f"{r['call_id']}.wav"),
             "variant": r["variant"], "duration_s": r["duration_s"],
             "sample_rate": r["sample_rate"], "channels": r["channels"]}
            for r in sorted(recordings, key=lambda r: r["call_id"])
        ],
    }

    evaluation = {
        "schema_version": 1,
        "note": "Labels. Only pipeline/evaluate.py may read this file, and only after predictions exist.",
        "calls": {
            r["call_id"]: {
                "source": r["source"], "original_filename": r["path"].name,
                "original_audio_path": rel(r["path"]), "sha256": sha256_file(r["path"]),
                "dialogue_id": r["dialogue_id"], "stufe": r["stufe"], "take": r["take"],
                "variant": r["variant"], "recording": dialogues[r["dialogue_id"]]["recording"],
                "duration_s": r["duration_s"],
                "label": dialogues[r["dialogue_id"]]["label"],
                "split": dialogues[r["dialogue_id"]]["split"],
                "group_id": dialogues[r["dialogue_id"]]["group_id"],
            }
            for r in sorted(recordings, key=lambda r: r["call_id"])
        },
        "dialogues": {k: dialogues[k] for k in sorted(dialogues)},
    }

    groups_by_split = defaultdict(list)
    for u in sorted(units, key=lambda u: u["group_id"]):
        call_ids = sorted(c for dlg in u["dialogue_ids"] for c in dialogues[dlg]["call_ids"])
        groups_by_split[u["split"]].append({"group_id": u["group_id"], "call_ids": call_ids})
    splits = {
        "schema_version": 1,
        "seed": seed,
        "holdout_fraction_target": frac,
        # kept free of level/label vocabulary on purpose: this file may be read by the pipeline side
        "policy": ("Groups never cross splits. A group holds all recordings of one script, or of two "
                   "near-identical scripts that only differ in context. dev: tune here. holdout: report "
                   "only, never tune. test: organizers' Testset_30, locked, final report only."),
        "splits": {
            s: {"call_ids": sorted(c for g in groups_by_split[s] for c in g["call_ids"]),
                "groups": groups_by_split[s]}
            for s in ("dev", "holdout", "test")
        },
    }

    def summary(split: str) -> dict:
        ds = [d for d in dialogues.values() if d["split"] == split]
        return {
            "dialogues": len(ds),
            "calls": sum(len(d["call_ids"]) for d in ds),
            "by_stufe": dict(sorted(Counter(f"Stufe{d['stufe']}" for d in ds).items())),
            "by_label": dict(sorted(Counter(d["label"] for d in ds).items())),
            "by_test_target": dict(sorted(Counter(d["test_target"] or "unspecified" for d in ds).items())),
            "dialogue_ids": sorted(d["dialogue_id"] for d in ds),
        }

    pool = [d for d in dialogues.values() if d["split"] in ("dev", "holdout")]
    hold = [d for d in pool if d["split"] == "holdout"]
    dev_targets = {d["test_target"] for d in pool if d["split"] == "dev"}
    hold_targets = {d["test_target"] for d in hold}
    for t in sorted(dev_targets - hold_targets):
        notes.append(f"test target '{t}' has no dialogue in holdout (too few dialogues to stratify on it too)")
    for t in sorted(hold_targets - dev_targets):
        notes.append(f"test target '{t}' has no dialogue in dev")
    for lab in sorted(LABELS):
        for stufe in (1, 2, 3):
            n_dev = sum(1 for d in pool if d["split"] == "dev" and d["label"] == lab and d["stufe"] == stufe)
            n_hold = sum(1 for d in hold if d["label"] == lab and d["stufe"] == stufe)
            if n_dev + n_hold and not (n_dev and n_hold):
                notes.append(f"Stufe{stufe}/{lab}: dev={n_dev}, holdout={n_hold} dialogues (not in both)")
    notes.append(f"holdout share of the case pool: {len(hold)}/{len(pool)} dialogues "
                 f"({len(hold) / len(pool):.0%}), target {frac:.0%}")

    report = {
        "readme_check": readme_checks,
        "totals": {"recordings": len(recordings), "dialogues": len(dialogues)},
        "issues": issues,
        "split_notes": notes,
        "split_stratification": split_stats["strata"],
        "split_summary": {s: summary(s) for s in ("dev", "holdout", "test")},
    }

    def dump(obj, path: Path):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dump(inference, man_dir / "inference.json")
    dump(evaluation, man_dir / "evaluation.json")
    dump(splits, split_dir / "dialogue_splits.json")
    dump(report, man_dir / "data_report.json")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path(os.environ.get("DATA_DIR", REPO_ROOT / "data")))
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--holdout-fraction", type=float, default=HOLDOUT_FRACTION)
    args = ap.parse_args(argv)
    report = build(args.data_dir, args.out, args.seed, args.holdout_fraction)
    print(json.dumps({k: report[k] for k in ("readme_check", "totals", "issues", "split_notes")},
                     ensure_ascii=False, indent=2))
    for s, v in report["split_summary"].items():
        print(f"{s:8s} {v['dialogues']:2d} dialogues {v['calls']:2d} calls  {v['by_stufe']}  {v['by_label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
