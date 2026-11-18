import pytest

from recovery import analyzer


def test_validate_coerces_bad_shapes():
    d = analyzer._validate({"category": "BOGUS", "root_cause": 5, "suggested_retry_cmd": "  "})
    assert d["category"] == "unknown" and d["root_cause"] == "5" and d["suggested_retry_cmd"] is None
    with pytest.raises(ValueError):
        analyzer._validate(["not", "a", "dict"])


def test_singleton_is_shared(monkeypatch):
    class Fake:
        def __init__(self, brain=None):
            pass
    monkeypatch.setattr(analyzer, "RecoveryAnalyzer", Fake)
    monkeypatch.setattr(analyzer, "_singleton", None)
    assert analyzer.get_analyzer() is analyzer.get_analyzer()
