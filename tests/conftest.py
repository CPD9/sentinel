"""Suite-wide hermetic defaults."""
import pytest


@pytest.fixture(autouse=True)
def _rules_decision_by_default(monkeypatch):
    """config/thresholds.json ships decision_source "direct_judge", which calls the LLM. Tests decide with facts ->
    rules unless they opt in (tests/test_pipeline_run.py fake_judge patches this back), so no test reaches a server."""
    from pipeline import runner
    monkeypatch.setattr(runner, "_decision_source", lambda: "rules")
