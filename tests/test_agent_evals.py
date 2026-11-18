"""The agent-level eval suite must pass (it is also a CI gate), plus planner robustness."""
import json
from pathlib import Path

from core.goal_planner import GoalPlanner
from evals import agent_run


def test_agent_eval_suite_passes():
    results = agent_run.run(agent_run.load_tasks(agent_run.DEFAULT_TASKS))
    failed = [(r.task_id, r.detail) for r in results if not r.passed]
    assert not failed, failed
    assert len(results) >= 20


def test_every_eval_kind_is_covered():
    kinds = {t["kind"] for t in agent_run.load_tasks(agent_run.DEFAULT_TASKS)}
    assert kinds == set(agent_run.RUNNERS)


def test_skipped_llm_steps_do_not_break_the_dependency_chain():
    class Brain:
        def ask(self, *a, **k):
            return json.dumps([
                {"description": "first", "tool": ""}, "junk",
                {"description": "", "tool": ""}, {"description": "second", "tool": ""},
            ])
    steps = GoalPlanner(brain=Brain()).decompose("do first and then second").steps
    assert [s.task_id for s in steps] == ["step_0", "step_1"]
    assert steps[1].depends_on == ["step_0"]  # not step_2/step_1 of a skipped item


def test_all_junk_plan_falls_back_to_deterministic():
    class Brain:
        def ask(self, *a, **k):
            return json.dumps(["x", 1, None])
    assert len(GoalPlanner(brain=Brain()).decompose("open notepad and then close it").steps) == 2


def test_tasks_file_is_valid_jsonl():
    for line in Path(agent_run.DEFAULT_TASKS).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            json.loads(line)
