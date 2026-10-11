"""Local-run fallback for the web app (web/app/run-api): the exact what-if simulator over one finished run.

Started once by the Next route handler and kept alive. Protocol: one JSON request per stdin line
  {"patch": {...}, "feedback": [FeedbackEntry, ...]}            → {"ok": SimulationResult}
  {"op": "hits", "keywords": <keywords.json document>}           → {"ok": {family: {term: n_segments}}}
  {"op": "rules"}                                                → {"ok": rules.yaml as a dict}
and {"error": {"status": 422|500, "detail": ...}} on failure.

It reuses pipeline/simulate.py (decide.py over the cached transcripts and facts: no ASR, no LLM, nothing written).
A reference-mode run keeps its transcripts and traces in transcripts_reference/ and traces_reference/; they are
exposed to load_inputs() through a temporary folder of symlinks, so the pipeline code stays untouched.
Usage: python web/scripts/run_simulate.py <artifacts_dir> <out_dir> <reference|asr>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import keywords as kw  # noqa: E402
from pipeline import simulate as sm  # noqa: E402
from pipeline.keywords import ConfigError  # noqa: E402
from pipeline.schemas import FeedbackEntry  # noqa: E402


def main() -> None:
    artifacts, out_dir, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    suffix = "_reference" if mode == "reference" else ""
    with tempfile.TemporaryDirectory() as tmp:
        view = Path(tmp)
        # a self-contained run folder (traces/, transcripts/ next to results/) wins over the shared artifacts
        own = lambda kind: out_dir / kind if (out_dir / kind).is_dir() else artifacts / f"{kind}{suffix}"  # noqa: E731
        (view / "traces").symlink_to(own("traces"))
        (view / "transcripts").symlink_to(own("transcripts"))
        if (artifacts / "analysis").exists():
            (view / "analysis").symlink_to(artifacts / "analysis")
        # only the calls of this run: shared artifacts may also hold traces of other runs (e.g. a test on a renamed WAV)
        ids = {p.stem for p in (out_dir / "results").glob("*.json")}
        sim = sm.Simulator([i for i in sm.load_inputs(view, out_dir) if not ids or i.call_id in ids])
        print(json.dumps({"ready": len(sim.inputs)}), flush=True)
        for line in sys.stdin:
            try:
                req = json.loads(line)
                if req.get("op") == "hits":
                    cfg = kw.parse_keywords(req["keywords"])
                    counts: dict[str, dict[str, int]] = {}
                    for i in sim.inputs:
                        for h in kw.find_hits(i.transcript, cfg):
                            fam = counts.setdefault(h.family, {})
                            fam[h.term] = fam.get(h.term, 0) + 1
                    print(json.dumps({"ok": counts}, ensure_ascii=False), flush=True)
                    continue
                if req.get("op") == "rules":
                    print(json.dumps({"ok": sim.raw.rules}, ensure_ascii=False), flush=True)
                    continue
                sim.feedback = {e["call_id"]: FeedbackEntry.from_dict(e) for e in req.get("feedback") or []
                                if e.get("call_id") in sim.baseline}
                res = sim.run(req.get("patch") or {})
                print(json.dumps({"ok": res.to_dict()}, ensure_ascii=False), flush=True)
            except ConfigError as e:
                print(json.dumps({"error": {"status": 422, "detail": [str(x) for x in getattr(e, "errors", [e])]}}), flush=True)
            except Exception as e:  # noqa: BLE001 - report, never crash the helper
                print(json.dumps({"error": {"status": 500, "detail": f"{type(e).__name__}: {e}"}}), flush=True)


if __name__ == "__main__":
    main()
