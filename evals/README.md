# Flexie Evals

A small, deterministic harness for measuring routing correctness, latency, and
regressions. Run it before and after any router change.

```bash
python -m evals.run
python -m evals.run --min-accuracy 0.95
python -m evals.run --tasks evals/tasks/routing.jsonl --output /tmp/routing.jsonl
```

## Task format

`evals/tasks/routing.jsonl`, one object per line:

```json
{"task_id": "route-001", "query": "open chrome", "expected": "app_op"}
```

## Adding tasks

Use real commands from the README or from user transcripts. Every routing bug
fixed should get a permanent task so it cannot regress silently.
