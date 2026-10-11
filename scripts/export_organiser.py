"""Write a run's results in the organisers' reference-packet format: Ergebnisse.csv, Ergebnisse.jsonl, Laufprotokoll.json.

    python scripts/export_organiser.py <run_dir> [--package <Testpaket folder>] [--out <dir>]

<run_dir> is a scripts/run_test_set.sh run (out/results.json, out/id_map.json, artifacts/traces/, wavs/). One row per
recording, clip_id = the original file stem (e.g. TEST-02):
  alert                decision == alarm (binary policy "review_no_auto_alert": a review is never an alert)
  manual_review        decision == review (incl. calls with a failed stage: never silently no alert)
  keyword_ids          K01..K11 groups our keyword matcher found verbatim (score >= 0.95), mapped through the
                       packet's 03_Referenzen/keywords.json (with --package), else the tracked copy
                       config/organiser_keywords.json (byte-identical to it and to the case list, sha256 8ec085ae...);
                       [] = explicitly none found
  entity_types         null = not reported (SENTINEL does not classify entity types)
  alert_audio_seconds  for an alarm: audio position (s) where the top finding's first evidence passage starts
  notes                top criterion, risk, confidence, stage errors
With --package, a sha256 mismatch against Auswahl.json or a selected clip that was not processed still writes every
file, but Laufprotokoll.json gets integrity.status = "failed" (with the lists), a banner is printed and the exit code
is 4, so nobody submits results for the wrong audio by accident.
Audio hashes in Laufprotokoll.json are those of the ORIGINAL files before any conversion (out/source_files.json,
written by run_test_set.sh), checked against the packet's Auswahl.json. Reads only our own outputs, the packet's
keyword list and Auswahl.json (run id, file hashes); never the packet's Soll files or any label.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYWORD_LIST = REPO_ROOT / "config" / "organiser_keywords.json"      # tracked copy; the packet's own file wins
FIELDS = ["clip_id", "alert", "manual_review", "keyword_ids", "entity_types", "alert_audio_seconds", "notes"]
VERBATIM = 0.95


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def keyword_index(path: Path = KEYWORD_LIST) -> tuple[dict[str, str], dict[str, list[str]]]:
    kl = json.loads(path.read_text(encoding="utf-8"))
    by_phrase = {_norm(p): k["id"] for k in kl["keywords"] for p in [*k.get("de", []), *k.get("gsw", [])]}
    by_family = {f: v["keywords"] for f, v in kl["families"].items()}
    return by_phrase, by_family


def keyword_ids(hits: list[dict], by_phrase: dict[str, str], by_family: dict[str, list[str]]) -> list[str]:
    ids = set()
    for h in hits:
        if float(h.get("score", 0)) < VERBATIM:
            continue
        k = by_phrase.get(_norm(h.get("term", ""))) or by_phrase.get(_norm(h.get("matched_text", "")))
        if not k and len(by_family.get(h.get("family", ""), [])) == 1:
            k = by_family[h["family"]][0]
        if k:
            ids.add(k)
    return sorted(ids)


def row(clip_id: str, res: dict, trace: dict | None, by_phrase, by_family) -> dict:
    dec = res["decision"]
    top = max(res.get("findings") or [], key=lambda f: f.get("risk", 0), default=None)
    sec = None
    if dec == "alarm" and top and top.get("evidence"):
        starts = [e["start_s"] for e in top["evidence"] if e.get("start_s") is not None]
        sec = round(min(starts), 2) if starts else None
    errs = [e["stage"] for e in res.get("stage_errors") or []]
    notes = [f"decision={dec}", f"risk={res.get('risk_score', 0):.2f}"]
    if res.get("confidence") is not None:
        notes.append(f"confidence={res['confidence']:.2f}")
    if top:
        notes.append(f"criterion={top['criterion']}")
    if errs:
        notes.append(f"stage_errors={','.join(errs)}")
    return {"clip_id": clip_id, "alert": dec == "alarm", "manual_review": dec == "review",
            "keyword_ids": keyword_ids((trace or {}).get("keyword_hits") or [], by_phrase, by_family) if trace else None,
            "entity_types": None, "alert_audio_seconds": sec, "notes": "; ".join(notes)}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def keyword_list_for(package: Path | None) -> Path:
    if package:
        p = package / "03_Referenzen" / "keywords.json"
        if not p.is_file():
            raise SystemExit(f"--package given but {p} is missing")
        return p
    return KEYWORD_LIST


def source_hashes(run_dir: Path) -> dict[str, str]:
    """stem -> sha256 of the original file (before conversion), from run_test_set.sh's out/source_files.json."""
    f = run_dir / "out" / "source_files.json"
    return {k: v["sha256"] for k, v in json.loads(f.read_text(encoding="utf-8")).items()} if f.is_file() else {}


def export(run_dir: Path, out: Path, package: Path | None = None, settings: str = "", started: str | None = None) -> dict:
    res_all = json.loads((run_dir / "out" / "results.json").read_text(encoding="utf-8"))
    im = run_dir / "out" / "id_map.json"
    idm = json.loads(im.read_text(encoding="utf-8"))["map"] if im.is_file() else {}
    cid2name = {v: k for k, v in idm.items()}
    kw_file = keyword_list_for(package)
    by_phrase, by_family = keyword_index(kw_file)
    originals = source_hashes(run_dir)
    rows, shas = [], {}
    for r in res_all["calls"]:
        name = cid2name.get(r["call_id"], f"{r['call_id']}.wav")
        clip = Path(name).stem
        tp = run_dir / "artifacts" / "traces" / f"{r['call_id']}.json"
        trace = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else None
        rows.append(row(clip, r, trace, by_phrase, by_family))
        if clip in originals:
            shas[clip] = originals[clip]
        elif (run_dir / "wavs" / name).is_file():            # no record of the original: hash what was processed
            shas[clip] = sha256(run_dir / "wavs" / name)
    rows.sort(key=lambda x: x["clip_id"])
    sel = json.loads((package / "Auswahl.json").read_text(encoding="utf-8")) if package and (package / "Auswahl.json").is_file() else {}
    mismatch = sorted(k for k, v in (sel.get("audio_sha256") or {}).items() if k in shas and shas[k] != v)
    missing = sorted(set(sel.get("clip_ids") or []) - {r["clip_id"] for r in rows})
    out.mkdir(parents=True, exist_ok=True)
    with (out / "Ergebnisse.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "alert": str(r["alert"]).lower(), "manual_review": str(r["manual_review"]).lower(),
                        "keyword_ids": "" if r["keyword_ids"] is None else ";".join(r["keyword_ids"]) or "[]",
                        "entity_types": "", "alert_audio_seconds": "" if r["alert_audio_seconds"] is None else r["alert_audio_seconds"]})
    (out / "Ergebnisse.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    try:
        version = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True).stdout.strip()
    except Exception:
        version = ""
    proto = {
        "run_id": res_all.get("run_id"), "selection_run_id": sel.get("run_id"), "team": "SENTINEL",
        "software_version": f"sentinel@{version}" if version else "sentinel",
        "settings": settings or "ASR faster-whisper large-v3-turbo (GPU), Apertus v1.5 8B multi-check judge, "
                                "config/thresholds.json (alarm 0.70, review 0.20); review = manual_review, never alert",
        "test_mode": "batch_file", "started_utc": started or res_all.get("created_at"),
        "audio_sha256": shas,
        "integrity": {"status": "failed" if (mismatch or missing) else "passed" if sel else "not_checked",
                      "checked_against": "Auswahl.json" if sel else None,
                      "sha256_mismatch": mismatch, "not_processed": missing},
        "notes": "; ".join(filter(None, [
            f"sha256 mismatch vs Auswahl.json: {mismatch}" if mismatch else "",
            f"not processed: {missing}" if missing else "",
            "" if originals else "audio_sha256 = processed WAV (no record of the original files)",
            f"keyword list: {kw_file.name} sha256 {sha256(kw_file)[:12]}",
            "entity_types not reported (null)", "alert_audio_seconds = audio position, not wall-clock latency"])),
    }
    (out / "Laufprotokoll.json").write_text(json.dumps(proto, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"rows": rows, "mismatch": mismatch, "missing": missing}


EXIT_INTEGRITY = 4


def banner(mismatch: list[str], missing: list[str]) -> str:
    bar = "!" * 78
    lines = [bar, "!!  INTEGRITY CHECK FAILED: the results do not cover the organisers' selection as given", bar]
    if mismatch:
        lines.append(f"!!  audio differs from Auswahl.json (sha256): {', '.join(mismatch)}")
    if missing:
        lines.append(f"!!  in Auswahl.json but not processed: {', '.join(missing)}")
    lines += ["!!  All result files were written; Laufprotokoll.json has integrity.status = failed.",
              "!!  Do not submit before the audio is checked against the packet.", bar]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--package", type=Path, help="the organisers' packet folder (for Auswahl.json run id and hashes)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--started-utc")
    a = ap.parse_args(argv)
    out = a.out or a.run_dir / "export"
    r = export(a.run_dir, out, a.package, started=a.started_utc or datetime.now(timezone.utc).isoformat())
    for x in r["rows"]:
        print(f"{x['clip_id']}: alert={x['alert']} review={x['manual_review']} keywords={x['keyword_ids']} "
              f"at={x['alert_audio_seconds']}")
    print(f"wrote {out}/Ergebnisse.csv, Ergebnisse.jsonl, Laufprotokoll.json")
    if r["mismatch"] or r["missing"]:
        print(banner(r["mismatch"], r["missing"]), file=sys.stderr)
        return EXIT_INTEGRITY
    return 0


if __name__ == "__main__":
    sys.exit(main())
