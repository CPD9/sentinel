"""Per-stage processing times from the runner's events (run.py --timings). Display / reporting only.

`TimingCollector` is an `on_event` callback: it keeps each call's stage `elapsed_s` (stage_finished / stage_failed)
and the call's total (job_finished). It never changes what a call decides; with --timings unset it is not created.
"""
from __future__ import annotations

import statistics
import threading


def stats(xs: list[float]) -> dict:
    """n, mean, median, p90 (nearest rank), min, max, rounded to ms. {} for no data."""
    if not xs:
        return {}
    s = sorted(xs)
    p90 = s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]
    return {"n": len(s), "mean": round(statistics.fmean(s), 3), "median": round(statistics.median(s), 3),
            "p90": round(p90, 3), "min": round(s[0], 3), "max": round(s[-1], 3)}


class TimingCollector:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls: dict[str, dict] = {}

    def __call__(self, ev: dict) -> None:
        cid, kind = ev.get("call_id"), ev.get("event")
        with self._lock:
            c = self.calls.setdefault(cid, {"call_id": cid, "stages": {}, "failed": [], "elapsed_s": None})
            if kind in ("stage_finished", "stage_failed") and ev.get("elapsed_s") is not None:
                st = ev["stage"]
                c["stages"][st] = round(c["stages"].get(st, 0.0) + float(ev["elapsed_s"]), 3)
                if kind == "stage_failed":
                    c["failed"].append(st)
            elif kind == "job_finished":
                c["elapsed_s"] = ev.get("elapsed_s")
                c["decision"] = ev.get("decision")

    def report(self, *, wall_s: float, workers: int, run_id: str) -> dict:
        calls = list(self.calls.values())
        names = sorted({s for c in calls for s in c["stages"]})
        return {
            "run_id": run_id, "workers": workers, "calls_n": len(calls), "wall_s": round(wall_s, 2),
            "throughput_calls_per_min": round(60 * len(calls) / wall_s, 2) if wall_s else None,
            "stage_errors": sum(len(c["failed"]) for c in calls),
            "per_call_s": stats([c["elapsed_s"] for c in calls if c["elapsed_s"] is not None]),
            "stages": {n: stats([c["stages"][n] for c in calls if n in c["stages"]]) for n in names},
            "calls": calls,
            "note": "stage times are per call as the runner measured them (perf_counter); with --workers > 1 calls "
                    "overlap, so per-call times include waiting for the shared LLM and CPU",
        }
