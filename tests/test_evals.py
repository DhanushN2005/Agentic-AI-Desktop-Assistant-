from core.router import IntentRouter
from evals.run import run_routing, summarize


def test_routing_eval_scores_known_task():
    tasks = [{"task_id": "t1", "query": "open chrome", "expected": "app_op"}]
    results = run_routing(IntentRouter(), tasks)
    summary = summarize(results)
    assert summary["total"] == 1
    assert summary["correct"] == 1
    assert summary["accuracy"] == 1.0


def test_routing_eval_reports_misses():
    tasks = [{"task_id": "t1", "query": "open chrome", "expected": "definitely_wrong"}]
    results = run_routing(IntentRouter(), tasks)
    assert results[0].correct is False
    assert summarize(results)["accuracy"] == 0.0
