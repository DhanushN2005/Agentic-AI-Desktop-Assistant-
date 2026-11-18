# Flexie — Benchmark & Hardening Report

Date: 2026-11-18 · Windows 11 · Python 3.10.9 · 12 CPUs
Reproduce: `python -m evals.bench` (speed + quality), `python -m evals.agent_run` (agent evals), `python -m evals.run` (routing eval), `pytest tests`.

## 1. Results at a glance

| Gate | Result |
|---|---|
| Test suite | **736 passed, 0 failed, 0 errors** (pytest exit 0) |
| Lint | `ruff check .` — all checks passed |
| Routing eval | **45 / 45** (100%) |
| Agent evals | **43 / 43** (100%): budget 3, confirm 5, executor_permission 2, forget 1, permission 6, plan 8, route 5, specialist 4, taint 5, usage 4 |

## 2. Speed (deterministic stack, fake LLM + stub tools, per call)

| Component | p50 | p95 | p99 | ops/sec |
|---|---:|---:|---:|---:|
| Intent routing (regex tier) | 1.48 ms | 3.56 ms | 4.86 ms | 587 |
| Permission check | 1 µs | 2 µs | 3 µs | 707,664 |
| Registry execute (gated, stub tool) | 8 µs | 17 µs | 33 µs | 95,676 |
| Scoped registry execute | 9 µs | 17 µs | 31 µs | 98,190 |
| Run-budget charge | 6 µs | 11 µs | 21 µs | 129,286 |
| Tool loop: 3 tool calls + answer | 119 µs | 281 µs | 439 µs | 6,552 |
| Plan decompose + sanitise (12 steps) | 175 µs | 383 µs | 564 µs | 4,570 |
| Plan execution (5 handler steps) | 996 µs | 2.07 ms | 2.70 ms | 877 |
| Memory: remember fact (4 stores) | 492 µs | 1.04 ms | 1.66 ms | 1,824 |
| Memory: forget (all stores) | 239 µs | 627 µs | 1.04 ms | 3,256 |

Cold import (fresh interpreter): `core.router` 155 ms · `core.agent_executor` 126 ms · `core.specialists` 98 ms · `core.goal_planner` 106 ms.

Takeaway: the safety layers are not a cost centre (permission + budget + scoped execute add ≈ 25 µs per tool call). Routing (~1.5 ms) is the slowest deterministic step, and it is still ~1000× cheaper than any LLM call.

### Before / after (same machine, measured in this session)

| Item | Before | After |
|---|---:|---:|
| Memory write (`MemoryManager.remember`) | 20.7 ms | 0.15 ms |
| Memory write (`MemorySystem.set_preference`) | 14.1 ms | 0.09 ms |
| Memory write (`SelfAwareness.learn_fact`) | 13.7 ms | 0.10 ms |

Cause: a new SQLite connection per write (journal files created/deleted each time on Windows). Fix: one shared WAL connection per database (`utils/sqlite_util.py`, 5 tests incl. 8-thread write test). Trade-off: WAL + `synchronous=NORMAL` can lose only the last few commits on OS crash / power loss.

## 3. What was fixed

**Security**
- `/health` no longer leaks the API token (issued only to allowlisted origins / `FLEXIE_EXTENSION_IDS`); CORS is an explicit allowlist.
- Permissions fail closed in `ToolRegistry.execute` (previously nothing checked); approvals are single-use; denied agent steps no longer "log and continue".
- `python.exec` cannot be told to skip the sandbox (operator policy only).
- Confirmation matcher is strict ("ok but first delete everything" is no longer consent).
- Prompt-injection boundary: tool output is fed back as untrusted data, and after web/email/MCP content enters a turn, effectful tools (click, fill, open) need approval until the next user turn.
- Model-generated plans are treated as untrusted (unknown tools dropped, types coerced, steps ≤ 8, timeouts capped, risk never taken from the model).

**Flow / architecture**
- Planner output was silently discarded (`s.command` AttributeError) — it now reaches `AgentExecutor` as a typed `TaskGraph`; handler-routed steps honour `blocked`/`awaiting_confirmation`.
- Controller wrapper dropped `is_subcommand`/`silent`/`depth` — now forwarded.
- One `_resolve_route`: deterministic router beats learned routes, router runs once per command, authoritative overrides skip the planner.
- Specialists (P2): hard-scoped registries, real tool loop over `Brain`, approvals (voice or UI), `delegate` tool, whole-word routing. Tag mismatches that left some specialists with no tools were fixed.
- Memory: `MemoryFacade` is the single remember/forget path (forget used to leave copies in other stores); wiki rewrite debounced; DB paths anchored to the project.
- Harness: `RunBudget` (steps / time / identical-call loop guard) on plan execution and specialist loops; agent-level evals gate CI; `evals/bench.py` added.
- Portability: `engines/system.py` imports without `pycaw`/`comtypes`/`pyautogui`.
- Hardcoded user name replaced by `FLEXIE_USER_NAME` (falls back to OS user).

Bugs found *by the new evals/tests* (not by reading): plan lost on one junk step; dependency gap after skipped steps (would deadlock); `\b` regex corrupted into a backspace by my own edit (caught by test); planner tool names that matched no registered tool.

## 4. Not done / not measured (read this before trusting the numbers)

- **No real-model measurement.** Plan quality, tool selection and task success with a live LLM were not run; all agent evals use a fake model. The Brain JSON tool protocol is untested against a real (especially small local) model.
- **No tokens / cost / energy per command** — telemetry for that does not exist yet. No head-to-head against OpenJarvis: I did not run it, and no published numbers were found.
- **Not exercised live:** voice approval, the browser extension with `FLEXIE_EXTENSION_IDS`, desktop/browser automation, full orchestrator startup, GitHub Actions run.
- **Still open from the OpenJarvis plan:** orchestrator is ~1,400 lines (target < 600); stores still exist side by side behind the facade (no single `MemoryBackend`); skill/MCP trust tiers and per-skill capability sets; native-vs-MCP shared execution path; ~dozens of `except Exception: logging.debug` blocks still hide failures; `engines/` and `core/handlers/` still mirror each other; signed installer / rollback.
- Regex/wording-based safety (`DangerGate`, permission classifier) still judges user phrasing for handler-routed steps; typed tool permissions are the stronger layer.
- The System specialist has exactly one tool (`app.open`) — no desktop tools are registered in the registry.
- Loop-guard thresholds (20 steps / 300 s / 3 repeats) are untuned defaults.
- Benchmark is one run on one machine; treat latencies as order-of-magnitude, not guarantees.

## 5. New configuration

| Variable | Purpose | Default |
|---|---|---|
| `FLEXIE_EXTENSION_IDS` | Extension IDs trusted to receive the API token (**required for the browser extension**) | none |
| `FLEXIE_USER_NAME` | Name used in greetings/prompts | OS username |
| `FLEXIE_DATA_DIR` | Where memory databases live | project folder |
| `FLEXIE_ALLOW_UNSANDBOXED_EXEC` | Allow `python.exec` outside the sandbox | off |
| `FLEXIE_RUN_MAX_STEPS` / `_SECONDS` / `_REPEATS` | Run budget / loop guard | 20 / 300 / 3 |

## 6. Token and cost telemetry (added after the figures above)

Every successful LLM call is recorded with provider, model, prompt/completion tokens (exact when the provider returns usage, else a flagged ~4 chars/token estimate), estimated cost and latency, attributed to the user command in flight. Read it with `python -m core.telemetry.report` or `GET /api/flexie/usage`. Cost is an estimate (blended per-provider rates; set `FLEXIE_PRICING_FILE` for real prices). Overhead: ~8 us per call in memory, ~102 us with the SQLite row. Not instrumented yet: the `agent_loop` chat path and the model-hub Ollama call. Full write-up: `FINAL_REPORT.html`.
