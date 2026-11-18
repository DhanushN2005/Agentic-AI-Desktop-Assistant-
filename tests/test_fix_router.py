import pytest

from core.router import IntentRouter

R = IntentRouter()


@pytest.mark.parametrize("q,intent", [
    ("what's on my screen", "vision_analyze"),
    ("describe my screen", "vision_analyze"),
    ("what's the weather in delhi", "weather"),
    ("what's 5 plus 3", "calc"),
    ("opne chrome", "app_op"),
    ("what time is it", "alarm"),
    ("stop", "conversational"),
    ("stop talking", "conversational"),
    ("stop pomodoro", "pomodoro"),
    ("what's the capital of france", "conversational"),
    ("what's my name", "conversational"),
    ("what is 15 percent of 200", "calc"),
    ("set an alarm for 7 am", "alarm"),
    ("list my todos", "todo_list"),
    ("take a picture of my screen", "vision_capture"),
    ("is it going to be hot today", "weather"),
])
def test_routes(q, intent):
    assert R.route(q)[0] == intent


def test_long_input_is_bounded():
    import time
    t = time.perf_counter()
    R.route("open " + "chrome " * 5000)
    assert time.perf_counter() - t < 0.5


def test_clear_memory_needs_confirmation():
    from core.danger_gate import DangerGate
    assert DangerGate().detect("clear memory")
    assert DangerGate().detect("forget everything")
    assert not DangerGate().detect("what is memory")


def test_routing_eval_suite_is_large_and_passes():
    from pathlib import Path

    from evals.run import load_tasks, run_routing
    tasks = load_tasks(Path("evals/tasks/routing.jsonl"))
    assert len(tasks) >= 150
    res = run_routing(R, tasks)
    assert sum(r.correct for r in res) / len(res) >= 0.9
