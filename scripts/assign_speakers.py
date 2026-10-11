"""Write <out>/<call_id>.json (schemas.SpeakerRoles): advisor/customer per ASR segment. Display only.

Uses pyannote clusters from <raw>/<call_id>.json when present ("acoustic + content"), else Apertus on the text
alone ("content only"). Apertus is called strictly one request at a time. Transcripts are read, never written.

    .venv/bin/python scripts/assign_speakers.py \
        --transcripts ~/Developer/sentinel-runs/s4t_0551_final/transcripts \
        --raw ~/Developer/sentinel-runs/speakers/_raw --out ~/Developer/sentinel-runs/speakers
    # comparison run without acoustics:
    ... --content-only --out ~/Developer/sentinel-runs/speakers/_content_only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import diarize, llm  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402
from pipeline.llm import DiskCache  # noqa: E402
from pipeline.schemas import SpeakerRoles  # noqa: E402

RUNS = Path.home() / "Developer/sentinel-runs"


def one(tpath: Path, raw_dir: Path, content_only: bool, client, cache: DiskCache) -> dict:
    blob = tpath.read_bytes()
    tr = json.loads(blob)
    segs = [s for s in tr["segments"] if s.get("start_s") is not None]
    raw = raw_dir / tpath.name
    rec = {"call_id": tr["call_id"], "transcript": {"path": str(tpath), "asr_model": tr.get("asr_model") or "",
                                                    "sha256": hashlib.sha256(blob).hexdigest()},
           "mapper": {"model": client.model, "prompt_version": diarize.PROMPT_VERSION, "provider": client.spec.name}}
    if not content_only and raw.is_file():
        r = json.loads(raw.read_text())
        joined = diarize.join_turns(segs, r["turns"])
        try:
            roles, why = diarize.map_clusters(segs, joined, client=client, cache=cache)
            rec |= {"label_source": "acoustic + content", "diarizer": r["model"], "cluster_roles": roles,
                    "rationale": why,
                    "turns": [{**t, "role": roles.get(t["cluster"], "unknown")} for t in r["turns"]],
                    "segments": [{**j, "role": roles.get(j["cluster"], "unknown")} for j in joined]}
            return rec
        except ValueError as e:
            print(f"  {tr['call_id']}: cluster mapping failed ({e}); falling back to content only", flush=True)
    labels = diarize.label_segments_content_only(segs, client=client, cache=cache)
    rec |= {"label_source": "content only", "segments": [{"id": s["id"], "role": labels[s["id"]]} for s in segs]}
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts", type=Path, default=RUNS / "s4t_0551_final/transcripts")
    ap.add_argument("--raw", type=Path, default=RUNS / "speakers/_raw")
    ap.add_argument("--out", type=Path, default=RUNS / "speakers")
    ap.add_argument("--content-only", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    client = llm.get_client()
    client.probe()
    cache = DiskCache(diarize.CACHE_DIR)
    paths = sorted(args.transcripts.glob("call_*.json"))
    if args.only:
        paths = [p for p in paths if p.stem in set(args.only)]
    for p in paths:                                   # one request at a time, by design
        t0 = time.time()
        rec = SpeakerRoles.from_dict(one(p, args.raw, args.content_only, client, cache)).to_dict()
        write_json_atomic(args.out / p.name, rec)
        n = {r: sum(s["role"] == r for s in rec["segments"]) for r in ("advisor", "customer", "unknown")}
        print(f"{p.stem}: {rec['label_source']:<18} {rec.get('cluster_roles') or ''} {n} {time.time() - t0:.1f}s",
              flush=True)


if __name__ == "__main__":
    main()
