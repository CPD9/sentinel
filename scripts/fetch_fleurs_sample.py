"""Stream a small FLEURS test sample per language for the language-ID validation (scripts/langid_validation.py).

    python -I scripts/fetch_fleurs_sample.py --out ~/Developer/sentinel-runs/fleurs [--n 50] [--langs fr_fr it_it de_de]

google/fleurs (CC BY 4.0, Conneau et al. 2022): reads data/<lang>/audio/test.tar.gz as a stream and stops after the
first --n WAV members, so only those bytes are downloaded (not the 350-660 MB archives). Only regular .wav members
are written, under their base name, into <out>/<lang>/; nothing in the archive is executed. Writes <out>/clips.json
in the format of scripts/pod_langid.py clips (id, path, gold Whisper language code, set "FLEURS test").
"""
from __future__ import annotations

import argparse
import json
import tarfile
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/{lang}/audio/test.tar.gz"
WHISPER = {"fr_fr": "fr", "it_it": "it", "de_de": "de"}


def fetch(lang: str, out: Path, n: int) -> tuple[list[dict], int]:
    dst = out / lang
    dst.mkdir(parents=True, exist_ok=True)
    clips, got = [], 0
    req = urllib.request.Request(BASE.format(lang=lang), headers={"User-Agent": "sentinel-langid-validation"})
    with urllib.request.urlopen(req, timeout=60) as resp:          # noqa: S310 - fixed huggingface.co URL
        counted = _Counting(resp)
        with tarfile.open(fileobj=counted, mode="r|gz") as tar:
            for m in tar:
                if not m.isreg() or not m.name.lower().endswith(".wav"):
                    continue
                name = Path(m.name).name
                f = tar.extractfile(m)
                if f is None:
                    continue
                (dst / name).write_bytes(f.read())
                clips.append({"id": f"{lang}/{name}", "path": str(dst / name), "lang": WHISPER[lang],
                              "group": name, "set": "FLEURS test"})
                got += 1
                if got >= n:
                    break
        return clips, counted.bytes


class _Counting:
    def __init__(self, raw):
        self.raw, self.bytes = raw, 0

    def read(self, k=-1):
        b = self.raw.read(k)
        self.bytes += len(b)
        return b


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--langs", nargs="+", default=list(WHISPER))
    a = ap.parse_args(argv)
    a.out = a.out.expanduser()
    all_clips = []
    for lang in a.langs:
        clips, nbytes = fetch(lang, a.out, a.n)
        all_clips += clips
        print(f"{lang}: {len(clips)} clips, {nbytes / 1e6:.1f} MB downloaded")
    (a.out / "clips.json").write_text(json.dumps(all_clips, indent=1), encoding="utf-8")
    print(f"wrote {a.out / 'clips.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
