import queue

from engines.automation import RuleEngine


class FakeOrch:
    def __init__(self):
        self.cmd_queue = queue.Queue()


def test_add_list_remove_rule():
    eng = RuleEngine(FakeOrch())
    assert eng.list_rules() == ["No automation rules."]
    assert eng.add_rule("r1", "always", "system report", cooldown=0) is True
    assert any("r1" in r for r in eng.list_rules())
    assert eng.remove_rule("r1") is True
    assert eng.list_rules() == ["No automation rules."]
    assert eng.remove_rule("missing") is False


def test_monitor_fires_always_condition():
    orch = FakeOrch()
    eng = RuleEngine(orch)
    eng.add_rule("always1", "always", "daily briefing", cooldown=0)
    eng.monitor_and_trigger()
    assert orch.cmd_queue.get_nowait() == "daily briefing"


def test_monitor_respects_cooldown():
    orch = FakeOrch()
    eng = RuleEngine(orch)
    eng.add_rule("cd", "always", "ping", cooldown=3600)
    eng.monitor_and_trigger()
    assert orch.cmd_queue.get_nowait() == "ping"
    eng.monitor_and_trigger()
    assert orch.cmd_queue.empty()


def test_evaluate_metrics_conditions():
    eng = RuleEngine(FakeOrch())
    assert eng._evaluate("cpu>10", cpu=50.0, ram=10.0, batt=100) is True
    assert eng._evaluate("cpu>90", cpu=50.0, ram=10.0, batt=100) is False
    assert eng._evaluate({"metric": "batt", "lt": 20}, cpu=0, ram=0, batt=10) is True
    assert eng._evaluate("batt_low", cpu=0, ram=0, batt=10) is True
    assert eng._evaluate(lambda ctx: ctx["cpu"] > 1, cpu=5, ram=0, batt=100) is True


def test_disabled_rule_never_fires():
    orch = FakeOrch()
    eng = RuleEngine(orch)
    eng.add_rule("off", "always", "noop", cooldown=0, enabled=False)
    eng.monitor_and_trigger()
    assert orch.cmd_queue.empty()
