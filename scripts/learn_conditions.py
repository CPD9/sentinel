"""Recall layer, "conditions after AI": learned REVIEW conditions over the calls the direct judge (S4) did not flag.

    python scripts/learn_conditions.py --run-dir ~/Developer/sentinel-runs/s4_0507 [--write]

ALARM stays the S4 verdict with >= 1 validated citation (unchanged). REVIEW may additionally come from a depth <= 3
decision tree over per-call signals:
  s4_risk                        the judge's risk score
  mined_pos / mined_neg          how many mined escalation / harmless n-grams the transcript contains: unigrams and
                                 bigrams present in >= 2 dialogue groups, ranked by log-odds with an informative
                                 Dirichlet prior (Monroe et al. 2008), top K each, mined from the TRAINING calls only
  kw_max_segments                most segments with hits of one keyword family (config/keywords.json)
  facts_request / _disclose / _credentials / _nonpublic / _client_data / _third_party / _secrecy
                                 counts of valid extracted facts with that act / info_type / flag
  facts_counter                  valid warn / refuse facts (counter-evidence, pushes towards no_alert)
Cross-validation: 3 folds over dev / Testset_30 / holdout (dialogue-grouped splits). Mining AND fitting happen inside
each fold on the two training splits; the held-out split is scored once. Compared on CV escalation F1, balanced
accuracy and review load (share of calls sent to a person): flag-all, facts -> rules, S4 alone, S4 + conditions.
Ship rule (set before measuring): S4 + conditions must beat S4 alone on CV balanced accuracy AND send <= 40 % of
calls to a person. --write fits on all 62 calls and writes config/keywords_mined.json + config/rules_learned.yaml.
Labels come only from pipeline.evaluate.escalation_targets (offline fitting on case data).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import decide as dec  # noqa: E402
from pipeline import evaluate  # noqa: E402
from pipeline import keywords as kw  # noqa: E402
from pipeline.io import write_json_atomic  # noqa: E402

SPLITS_FILE = REPO_ROOT / "artifacts" / "splits" / "dialogue_splits.json"
SPLITS = ("dev", "test", "holdout")
TOP_K = 25
ALPHA = 0.5                      # prior strength per n-gram, scaled by its overall frequency
MAX_REVIEW_LOAD = 0.40
WORD = re.compile(r"[a-zäöüß]{3,}")
FEATURES = ("s4_risk", "mined_pos", "mined_neg", "kw_max_segments", "facts_request", "facts_disclose",
            "facts_credentials", "facts_nonpublic", "facts_client_data", "facts_third_party", "facts_secrecy",
            "facts_counter")


def ngrams(text: str) -> set[str]:
    w = WORD.findall(text.lower())
    return set(w) | {f"{a} {b}" for a, b in zip(w, w[1:])}


def load(run_dir: Path) -> tuple[list[str], dict, dict, dict]:
    sp = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))["splits"]
    ids = [c for s in SPLITS for c in sp[s]["call_ids"]]
    group = {c: g["group_id"] for s in SPLITS for g in sp[s]["groups"] for c in g["call_ids"]}
    split = {c: s for s in SPLITS for c in sp[s]["call_ids"]}
    cfg = dec.load_config()
    calls = {}
    for c in ids:
        t = json.loads((run_dir / "transcripts" / f"{c}.json").read_text(encoding="utf-8"))
        tr = json.loads((run_dir / "traces" / f"{c}.json").read_text(encoding="utf-8"))
        jd = json.loads((run_dir / "judge" / f"{c}.json").read_text(encoding="utf-8"))
        from pipeline.schemas import Transcript
        T = Transcript.from_dict(t)
        fam: dict[str, set] = {}
        for h in kw.find_hits(T, cfg.keywords):
            fam.setdefault(h.family, set()).add(h.segment_id)
        facts = [f for f in tr["facts"] if f["valid"]]
        s4_flag = jd["decision"] != "no_alert"
        calls[c] = {"grams": set().union(*(ngrams(s["text"]) for s in t["segments"])) if t["segments"] else set(),
                    "segments": t["segments"], "s4_flag": s4_flag,
                    "s4_alarm": jd["decision"] == "alarm" and any(x["valid"] for x in jd["citations"]),
                    "base": {"s4_risk": jd["risk"], "kw_max_segments": max((len(v) for v in fam.values()), default=0),
                             "facts_request": sum(f["act"] == "request" for f in facts),
                             "facts_disclose": sum(f["act"] == "disclose" for f in facts),
                             "facts_credentials": sum(f["info_type"] == "credentials" for f in facts),
                             "facts_nonpublic": sum(f["info_type"] == "nonpublic_info" for f in facts),
                             "facts_client_data": sum(f["info_type"] == "client_data" for f in facts),
                             "facts_third_party": sum(f.get("recipient_third_party") is True for f in facts),
                             "facts_secrecy": sum(f.get("secrecy_cue") is True for f in facts),
                             "facts_counter": sum(f["act"] in ("warn", "refuse") for f in facts)},
                    "facts": facts, "risk_rules": max((r["risk"] for r in tr["rules"]), default=0.0)}
    return ids, calls, group, split


def mine(train: list[str], calls: dict, group: dict, y: dict) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Log-odds with an informative Dirichlet prior over call-level n-gram presence, n-grams in >= 2 dialogue groups."""
    groups_of: dict[str, set] = {}
    for c in train:
        for g in calls[c]["grams"]:
            groups_of.setdefault(g, set()).add(group[c])
    vocab = [g for g, gs in groups_of.items() if len(gs) >= 2]
    pos = [c for c in train if y[c]]
    neg = [c for c in train if not y[c]]
    cp = Counter(g for c in pos for g in calls[c]["grams"])
    cn = Counter(g for c in neg for g in calls[c]["grams"])
    tot = Counter(g for c in train for g in calls[c]["grams"])
    n_p, n_n = sum(cp[g] for g in vocab), sum(cn[g] for g in vocab)
    a0 = ALPHA * len(vocab)
    out = []
    for g in vocab:
        a = ALPHA * len(vocab) * tot[g] / max(1, sum(tot[v] for v in vocab)) or 0.01
        d = math.log((cp[g] + a) / (n_p + a0 - cp[g] - a)) - math.log((cn[g] + a) / (n_n + a0 - cn[g] - a))
        out.append((g, d / math.sqrt(1 / (cp[g] + a) + 1 / (cn[g] + a))))
    out.sort(key=lambda x: -x[1])
    return out[:TOP_K], [(g, z) for g, z in out[::-1][:TOP_K]]


def features(c: str, calls: dict, lex_pos: set, lex_neg: set) -> dict:
    g = calls[c]["grams"]
    return {**calls[c]["base"], "mined_pos": len(g & lex_pos), "mined_neg": len(g & lex_neg)}


def fit(train: list[str], calls: dict, group: dict, y: dict):
    from sklearn.tree import DecisionTreeClassifier
    lp, ln = mine(train, calls, group, y)
    lex_pos, lex_neg = {g for g, _ in lp}, {g for g, _ in ln}
    rows = [c for c in train if not calls[c]["s4_flag"]]            # conditions only act where S4 did not flag
    X = [[features(c, calls, lex_pos, lex_neg)[f] for f in FEATURES] for c in rows]
    tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=5, class_weight="balanced", random_state=0)
    tree.fit(X, [y[c] for c in rows])
    # cut-off on the leaf probability, chosen on the TRAINING calls: best balanced accuracy with review load <= cap
    model = [tree, lp, ln, 1.01]
    best = None
    for cut in sorted({p for p in tree.predict_proba(X)[:, 1]} | {1.01}):
        model[3] = cut
        s = summary({c: decide(c, calls, model) for c in train})
        if s["review_load"] <= MAX_REVIEW_LOAD and (best is None or s["bacc"] > best[0]):
            best = (s["bacc"], cut)
    model[3] = best[1] if best else 1.01
    return tuple(model)


def decide(c: str, calls: dict, model) -> str:
    tree, lp, ln, cut = model
    if calls[c]["s4_alarm"]:
        return "alarm"
    if calls[c]["s4_flag"]:
        return "review"
    f = features(c, calls, {g for g, _ in lp}, {g for g, _ in ln})
    return "review" if tree.predict_proba([[f[k] for k in FEATURES]])[0][1] >= cut else "no_alert"


def summary(dec_: dict[str, str]) -> dict:
    m = evaluate.score_decisions(dec_)["all"]
    e = m["escalation"]
    rec, spec = e["tp"] / max(1, e["tp"] + e["fn"]), e["tn"] / max(1, e["tn"] + e["fp"])
    return {"esc_p": e["precision"], "esc_r": round(rec, 4), "esc_f1": e["f1"], "bacc": round((rec + spec) / 2, 4),
            "review_load": round(sum(d != "no_alert" for d in dec_.values()) / len(dec_), 4),
            "false_alarms": m["three_class"]["confusion"]["no_alert"]["alarm"]}


def tree_text(tree, lp, ln, cut=None) -> str:
    from sklearn.tree import export_text
    return export_text(tree, feature_names=list(FEATURES), show_weights=True) + f"review when P(escalate) >= {cut}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    ids, calls, group, split = load(a.run_dir)
    y = evaluate.escalation_targets(ids)
    by = {s: [c for c in ids if split[c] == s] for s in SPLITS}

    methods = {"flag-all": {}, "facts -> rules": {}, "S4 alone": {}, "S4 + conditions": {}}
    oof = {k: {} for k in methods}
    folds = {k: {} for k in methods}
    for held in SPLITS:
        train = [c for c in ids if split[c] != held]
        test = by[held]
        model = fit(train, calls, group, y)
        # facts -> rules: escalation threshold on its risk chosen on train by balanced accuracy
        cands = sorted({calls[c]["risk_rules"] for c in train}) + [2.0]
        t = max(cands, key=lambda t: (summary({c: "review" if calls[c]["risk_rules"] >= t else "no_alert"
                                               for c in train})["bacc"], t))
        d = {"flag-all": {c: "review" for c in test},
             "facts -> rules": {c: "review" if calls[c]["risk_rules"] >= t else "no_alert" for c in test},
             "S4 alone": {c: "alarm" if calls[c]["s4_alarm"] else "review" if calls[c]["s4_flag"] else "no_alert"
                          for c in test},
             "S4 + conditions": {c: decide(c, calls, model) for c in test}}
        for k in methods:
            folds[k][held] = summary(d[k])
            oof[k].update(d[k])
    rows = {}
    for k in methods:
        vals = [folds[k][s]["bacc"] for s in SPLITS]
        rows[k] = {"folds": folds[k], "cv_bacc_mean": round(sum(vals) / 3, 4), "cv_bacc_range": [min(vals), max(vals)],
                   "oof": summary(oof[k])}
        o = rows[k]["oof"]
        f = lambda x: "n/a" if x is None else f"{x:.2f}"
        print(f"{k:16s} CV bacc {rows[k]['cv_bacc_mean']:.2f} ({min(vals):.2f}-{max(vals):.2f}) | OOF esc P {f(o['esc_p'])} "
              f"R {f(o['esc_r'])} F1 {f(o['esc_f1'])} bacc {f(o['bacc'])} | review load {o['review_load']:.0%} | "
              f"FA {o['false_alarms']} | per fold " + ", ".join(f"{s}: P {f(folds[k][s]['esc_p'])} R {f(folds[k][s]['esc_r'])}"
                                                               for s in SPLITS))
    win = (rows["S4 + conditions"]["cv_bacc_mean"] > rows["S4 alone"]["cv_bacc_mean"]
           and rows["S4 + conditions"]["oof"]["review_load"] <= MAX_REVIEW_LOAD)
    print(f"ship rule (beats S4 alone on CV bacc AND review load <= {MAX_REVIEW_LOAD:.0%}): {'PASS' if win else 'FAIL'}")
    model = fit(ids, calls, group, y)
    print("tree fitted on all 62 (for the record):\n" + tree_text(*model))
    doc_path = REPO_ROOT / "artifacts" / "metrics" / "conditions_cv.json"
    write_json_atomic(doc_path, {"methods": rows, "ship_rule_pass": win, "top_k": TOP_K, "features": FEATURES,
                                 "mined_all62": {"escalation": model[1], "harmless": model[2]},
                                 "tree_all62": tree_text(*model)})
    print(f"written {doc_path.relative_to(REPO_ROOT)}")
    if a.write and win:
        write_json_atomic(REPO_ROOT / "config" / "keywords_mined.json",
                          {"_comment": "mined by scripts/learn_conditions.py on all 62 case calls (log-odds, informative "
                                       "prior, n-grams in >= 2 dialogue groups)", "escalation": model[1],
                           "harmless": model[2]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
