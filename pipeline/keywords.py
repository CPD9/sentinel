"""Step 3: deterministic fuzzy keyword matching over transcript segments.

Reads config/keywords.json (families -> terms -> variants, `fuzzy_threshold`, `min_fuzzy_len`) and emits
`KeywordHit`s. Matching is token-aligned (no partial-word hits): a window of as many tokens as the term is
compared with `difflib.SequenceMatcher`; terms shorter than `min_fuzzy_len` characters (PIN, TAN) must match exactly.

Keyword hits never enter the extraction prompt or the LLM cache key: this module imports nothing from
pipeline.llm, and `llm.extraction_cache_key` has no keyword input.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from pipeline.schemas import CRITERION_BY_FAMILY, KeywordHit, Transcript

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYWORDS_FILE = REPO_ROOT / "config" / "keywords.json"
_TOKEN = re.compile(r"\w+", re.UNICODE)


class ConfigError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Family:
    name: str
    criterion: str
    terms: list[str]
    variants: dict[str, list[str]] = field(default_factory=dict)
    label: str = ""


@dataclass
class KeywordConfig:
    families: dict[str, Family]
    fuzzy_threshold: float = 0.85
    min_fuzzy_len: int = 5


def parse_keywords(d: dict) -> KeywordConfig:
    errs: list[str] = []
    ft, ml = d.get("fuzzy_threshold", 0.85), d.get("min_fuzzy_len", 5)
    if not isinstance(ft, (int, float)) or not 0 < ft <= 1:
        errs.append("fuzzy_threshold must be a number in (0, 1]")
    if not isinstance(ml, int) or ml < 1:
        errs.append("min_fuzzy_len must be a positive integer")
    fams: dict[str, Family] = {}
    for name, f in (d.get("families") or {}).items():
        if name not in CRITERION_BY_FAMILY:
            errs.append(f"families.{name}: not a known family {tuple(CRITERION_BY_FAMILY)}")
            continue
        terms = f.get("terms", [])
        if not isinstance(terms, list) or not all(isinstance(t, str) and _tokens(t) for t in terms):
            errs.append(f"families.{name}.terms must be a list of non-empty strings")
            continue
        variants = f.get("variants", {})
        if not isinstance(variants, dict) or any(k not in terms or not isinstance(v, list) or not all(isinstance(x, str) for x in v)
                                                 for k, v in variants.items()):
            errs.append(f"families.{name}.variants must map configured terms to lists of strings")
            continue
        bad = [(k, x) for k, v in variants.items() for x in v if not _tokens(x)]
        if bad:
            errs += [f"families.{name}.variants.{k}: {x!r} is empty or has no word characters" for k, x in bad]
            continue
        fams[name] = Family(name, CRITERION_BY_FAMILY[name], list(terms), {k: list(v) for k, v in variants.items()},
                            f.get("label", ""))
    if errs:
        raise ConfigError(errs)
    return KeywordConfig(fams, float(ft), ml)


def load_keywords(path: Path = KEYWORDS_FILE) -> KeywordConfig:
    return parse_keywords(json.loads(Path(path).read_text(encoding="utf-8")))


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group().casefold(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _match_span(seg_tokens: list[tuple[str, int, int]], form: str, cfg: KeywordConfig):
    """Yield (score, first_token, last_token_exclusive) for windows of the form's length that pass the threshold."""
    ft = [t for t, _, _ in _tokens(form)]
    n, target = len(ft), " ".join(ft)
    exact_only = len(target) < cfg.min_fuzzy_len
    words = [t for t, _, _ in seg_tokens]
    for i in range(len(words) - n + 1):
        cand = " ".join(words[i:i + n])
        if cand == target:
            score = 1.0
        elif exact_only:
            continue
        else:
            sm = SequenceMatcher(None, cand, target)
            if sm.real_quick_ratio() < cfg.fuzzy_threshold or sm.quick_ratio() < cfg.fuzzy_threshold:
                continue
            score = sm.ratio()
        if score >= cfg.fuzzy_threshold:
            yield score, i, i + n


def find_hits(transcript: Transcript, cfg: KeywordConfig) -> list[KeywordHit]:
    """All keyword hits, ordered by segment, position, family, term; ids H1.. are deterministic."""
    found = []
    for si, seg in enumerate(transcript.segments):
        toks = _tokens(seg.text)
        cands = []
        for fam in cfg.families.values():
            for term in fam.terms:
                for form in [term, *fam.variants.get(term, [])]:
                    for score, a, b in _match_span(toks, form, cfg):
                        cands.append((-score, -(b - a), fam.name, term, a, b))
        taken: list[tuple[str, int, int]] = []   # greedy: best score first, one hit per family per place
        for negscore, _, fam, term, a, b in sorted(cands):
            if any(f == fam and a < tb and ta < b for f, ta, tb in taken):
                continue
            taken.append((fam, a, b))
            found.append((si, a, fam, term, -negscore, seg.id, seg.text[toks[a][1]:toks[b - 1][2]]))
    found.sort(key=lambda x: x[:4])
    return [KeywordHit(f"H{i}", fam, term, text, sid, round(score, 4))
            for i, (_, _, fam, term, score, sid, text) in enumerate(found, 1)]
