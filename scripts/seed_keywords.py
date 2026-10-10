"""Seed config/keywords.json from the case keyword list (read-only).

    python scripts/seed_keywords.py [--src data/case/Stichwortliste.json] [--out config/keywords.json] [--force]

Terms = the case `de` forms of each family's K-ids (deduped, order kept). `variants[term]` is seeded with the
`gsw` form at the same position (all of them if the lists differ in length) that differs from the term (provisional; Carl edits them). Refuses to overwrite an
existing output without --force because the file is hand-edited afterwards.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from pipeline.schemas import CRITERION_BY_FAMILY  # noqa: E402


def seed(case: dict) -> dict:
    by_id = {k["id"]: k for k in case["keywords"] if k.get("enabled", True)}
    families = {}
    for fam, spec in case["families"].items():
        terms: list[str] = []
        variants: dict[str, list[str]] = {}
        for kid in spec["keywords"]:
            k = by_id.get(kid)
            if k is None:
                continue
            gsw = k.get("gsw", [])
            de = k.get("de", [])
            for i, term in enumerate(de):
                if term not in terms:
                    terms.append(term)
                    variants[term] = []
                # the case lists are positionally aligned (de[i] <-> gsw[i]); if lengths differ, attach all
                mine = [gsw[i]] if len(gsw) == len(de) else gsw
                for g in mine:
                    if g.casefold() != term.casefold() and g not in variants[term]:
                        variants[term].append(g)
        families[fam] = {"criterion": CRITERION_BY_FAMILY[fam], "label": spec["label"],
                         "terms": terms, "variants": variants}
    return {
        "source": f"{case.get('version')} ({case.get('status')}); gsw variants are provisional case spellings",
        "fuzzy_threshold": 0.85,
        "min_fuzzy_len": 5,
        "families": families,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=REPO_ROOT / "data/case/Stichwortliste.json")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "config/keywords.json")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.out.exists() and not a.force:
        print(f"{a.out} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    out = seed(json.loads(a.src.read_text(encoding="utf-8")))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {a.out}: " + ", ".join(f"{f}={len(v['terms'])}" for f, v in out["families"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
