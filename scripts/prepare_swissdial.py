"""Extract a small SwissDial 1.1 subset as a dialect-robustness set for the ASR bake-off.

SwissDial (one folder per dialect speaker, `<dialect>/ch_<dialect>_<id>.wav`, sentence ids shared
across dialects; `sentences_ch_de_transcribed.json` holds the Standard German `de` and the
`ch_<dialect>` transcripts with numbers written out) is NOT case data. It never enters
artifacts/manifests/{inference,evaluation}.json or the dialogue splits.

Reads the original tar in place (no full 10 GB extraction, the tar is never modified) and writes:
  data/swissdial/data1.1/{README.txt,LICENSE.txt,sentences_*.json,<dialect>/<sampled>.wav}
  artifacts/manifests/swissdial.json   [{dialect, utt_id, sentence_id, audio_path, ref_de, ref_gsw}]

The same N sentence ids are sampled for every dialect (seeded), so dialects are directly comparable.

Usage: python scripts/prepare_swissdial.py [--tar ~/Downloads/data1.1.tar] [--per-dialect 20]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAR = Path.home() / "Downloads" / "data1.1.tar"
DEFAULT_OUT = REPO_ROOT / "data" / "swissdial"
MANIFEST = REPO_ROOT / "artifacts" / "manifests" / "swissdial.json"
DEFAULT_SEED = 20261010
TRANSCRIPTS = "sentences_ch_de_transcribed.json"
META_FILES = ("README.txt", "LICENSE.txt", TRANSCRIPTS, "sentences_ch_de_numerics.json")
WAV_RE = re.compile(r"^(?P<root>[^/]+)/(?P<dialect>[a-z]{2})/ch_(?P=dialect)_(?P<id>\d+)\.wav$")


def stable_key(seed: int, *parts: str) -> str:
    return hashlib.sha256(":".join([str(seed), *parts]).encode()).hexdigest()


def sample_ids(wavs: dict[str, dict[int, str]], sentences: dict[int, dict], n: int, seed: int) -> list[int]:
    """Sentence ids that exist as audio in every dialect and have a transcript for each of them."""
    dialects = sorted(wavs)
    common = set.intersection(*(set(v) for v in wavs.values()))
    usable = [i for i in common if i in sentences and sentences[i].get("de", "").strip()
              and all(sentences[i].get(f"ch_{d}", "").strip() for d in dialects)]
    if len(usable) < n:
        raise ValueError(f"only {len(usable)} sentence ids are usable across all dialects, need {n}")
    return sorted(sorted(usable, key=lambda i: stable_key(seed, str(i)))[:n])


def build(tar_path: Path, out_dir: Path, manifest: Path, n: int, seed: int) -> dict:
    with tarfile.open(tar_path, "r:") as tar:
        members = {m.name: m for m in tar.getmembers()}
        wavs: dict[str, dict[int, str]] = defaultdict(dict)
        roots = set()
        for name in members:
            if m := WAV_RE.match(name):
                wavs[m["dialect"]][int(m["id"])] = name
                roots.add(m["root"])
        if len(roots) != 1:
            raise ValueError(f"expected one top-level folder in {tar_path}, got {sorted(roots)}")
        root = roots.pop()
        sentences = {int(s["id"]): s for s in json.load(tar.extractfile(members[f"{root}/{TRANSCRIPTS}"]))}
        ids = sample_ids(wavs, sentences, n, seed)

        wanted = [f"{root}/{f}" for f in META_FILES if f"{root}/{f}" in members]
        wanted += [wavs[d][i] for d in sorted(wavs) for i in ids]
        for name in wanted:
            dst = out_dir / name
            if dst.is_file() and dst.stat().st_size == members[name].size:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            with tar.extractfile(members[name]) as src, tmp.open("wb") as f:
                while chunk := src.read(1 << 20):
                    f.write(chunk)
            tmp.replace(dst)

    def rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(REPO_ROOT))
        except ValueError:
            return str(p.resolve())

    utts = [{"dialect": d, "utt_id": f"sd_{d}_{i:04d}", "sentence_id": i,
             "audio_path": rel(out_dir / wavs[d][i]),
             "ref_de": sentences[i]["de"], "ref_gsw": sentences[i][f"ch_{d}"]}
            for d in sorted(wavs) for i in ids]
    out = {"schema_version": 1, "source": f"SwissDial {root} ({tar_path.name})", "seed": seed,
           "per_dialect": n, "dialects": sorted(wavs), "sentence_ids": ids,
           "note": "Dialect robustness set only. Never part of the case manifests or splits.",
           "utterances": utts}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tar", type=Path, default=DEFAULT_TAR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--per-dialect", type=int, default=20)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args(argv)
    if not args.tar.is_file():
        print(f"SwissDial tar not found: {args.tar}", file=sys.stderr)
        return 1
    out = build(args.tar, args.out, args.manifest, args.per_dialect, args.seed)
    print(f"{len(out['utterances'])} utterances ({out['per_dialect']} x {len(out['dialects'])} dialects: "
          f"{', '.join(out['dialects'])}) -> {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
