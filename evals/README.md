# Flexie Evals

Small, deterministic harnesses (no network, no real model) for measuring routing
correctness, agent behaviour around the model, latency, and regressions. Run them
before and after any router, permission, planner or memory change. CI also runs them
(`.github/workflows/ci.yml`, with pytest and ruff).

| Command | What it checks | Tasks |
|---|---|---|
| `python -m evals.run` | Which intent the regex router picks | `tasks/routing.jsonl` (158 cases) |
| `python -m evals.agent_run` | The agent *around* the model: plan sanitising, permissions, run budgets/loop guard, confirmation strictness, taint rules, memory forgetting, usage tracking, wording | `tasks/agent.jsonl` (59 tasks) |
| `python -m evals.bench` | Speed of the deterministic stack plus both quality gates; writes `results/bench-<timestamp>.json` and `.md` | uses both task files |

```bash
python -m evals.run                          # default pass threshold 0.9
python -m evals.run --min-accuracy 0.95
python -m evals.run --tasks evals/tasks/routing.jsonl --output /tmp/routing.jsonl
python -m evals.agent_run --min-pass 1.0
python -m evals.bench
```

`evals.run` exits non-zero when accuracy is below `--min-accuracy` (default **0.9**) and
also when the task file is empty. Results are written to `evals/results/` (git-ignored).

## Task formats

`evals/tasks/routing.jsonl`, one object per line:

```json
{"task_id": "route-001", "query": "open chrome", "expected": "app_op"}
```

`evals/tasks/agent.jsonl` holds the agent-level cases (see `evals/agent_run.py` for the
supported `kind` values); blank lines and `#` comment lines are ignored by both loaders.

## Adding tasks

Use real commands from the README or from user transcripts. Every routing bug
fixed should get a permanent task so it cannot regress silently. The routing set covers
typos, ambiguous phrasing, negatives (sentences that must *not* trigger an action) and
questions about Flexie itself (`awareness`). Note that part of the set was written from
outputs the router already produced, so a 100% score is an upper bound, not a guarantee
for unseen phrasing.

## What these do not measure

Real-model plan quality, tool-selection accuracy or task success; real voice, desktop or
browser latency; end-to-end start-up (timed separately). Everything here uses a fake model
and stub tool bodies. See `BENCHMARK_REPORT.md` for the current numbers.
