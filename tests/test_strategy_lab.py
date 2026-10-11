"""scripts/strategy_lab.py: label-free strategy logic, ensemble vote, agreement, bootstrap. No network, no data."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import strategy_lab as sl  # noqa: E402
from pipeline.schemas import KeywordHit  # noqa: E402


def hit(i, family, seg):
    return KeywordHit(f"k{i:03d}", family, "Passwort", "Passwort", seg, 1.0)


def test_keywords_only_thresholds():
    assert sl.keywords_only([])[0] == "no_alert"
    d, risk, why = sl.keywords_only([hit(1, "access", "T001"), hit(2, "access", "T001")])
    assert d == "review" and "credential_sharing" in why and "1 segment" in why    # same segment counts once
    d, risk, _ = sl.keywords_only([hit(i, "access", f"T00{i}") for i in range(1, sl.ALARM_SEGMENTS + 1)])
    assert d == "alarm" and risk == 1.0


def test_ensemble_majority_and_disagreement_is_review():
    assert sl.ensemble(["alarm", "alarm", "no_alert"]) == "alarm"
    assert sl.ensemble(["no_alert", "review", "no_alert"]) == "no_alert"
    assert sl.ensemble(["alarm", "review", "no_alert"]) == "review"
    assert sl.ENSEMBLE_OF == ("S1", "S3", "S4") and "holdout" not in sl.TUNE_SPLITS


def test_agreement_matrix():
    rows = {"A": [{"decision": d} for d in ("alarm", "review", "no_alert", "no_alert")],
            "B": [{"decision": d} for d in ("alarm", "review", "no_alert", "alarm")]}
    m = sl.agreement(rows)
    assert m["A"]["A"] == {"agree": 1.0, "kappa": 1.0}
    assert m["A"]["B"]["agree"] == 0.75 and m["A"]["B"] == m["B"]["A"] and 0 < m["A"]["B"]["kappa"] < 1


def test_bootstrap_paired_and_bounded():
    gold = ["alarm", "no_alert", "review", "no_alert", "alarm", "no_alert"]
    good = [{"gold": g, "pred": g} for g in gold]
    bad = [{"gold": g, "pred": "no_alert"} for g in gold]
    b = sl.bootstrap({"good": good, "bad": bad}, n=200)
    assert b["ci95"]["good"]["esc_f1"] == [1.0, 1.0]
    assert b["p_esc_f1_greater"]["good"]["bad"] >= 0.95 and b["p_esc_f1_greater"]["bad"]["good"] == 0.0
