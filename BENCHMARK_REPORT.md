# Flexie — Benchmark & Hardening Report

Date: 2026-11-18 (evening re-run) · Windows 11 · Python 3.10.9 · 12 CPUs
Reproduce: `python -m evals.bench` (speed + quality; writes `evals/results/bench-<ts>.json/.md`), `python -m evals.agent_run` (agent evals), `python -m evals.run` (routing eval), `pytest tests`.

This report replaces the earlier version (736 tests, 45 routing cases, 43 agent evals). All numbers below were measured again after the fix rounds described in `docs/FIX_CHECKLIST.md`.

## 1. Results at a glance

| Gate | Result |
|---|---|
| Test suite | **2,119 passed, 2 skipped, 0 failed** (72 test files; ~4 minutes, mostly tests that start real `git`/`npm` processes) |
| Lint | `ruff check .` — all checks passed |
| Routing eval | **158 / 158** (100%), default pass threshold 0.9; part of the set was written from outputs the router already produced, so treat 100% as an upper bound |
| Agent evals | **59 / 59** (100%): budget 3, confirm 5, executor_permission 2, forget 1, permission 6, plan 10, route 6, specialist 4, split 6, taint 5, usage 4, wording 7 |
| Router size | 96 intents, 197 natural-language overrides |
| Source size | ~47,100 lines of Python (tests ~19,000) |

## 2. Speed (deterministic stack, fake LLM + stub tools, per call)

One run on one machine. The "before" column is the baseline run of 2026-11-18 14:14 (`evals/results/bench-20261118-141406.json`), which preceded the security, memory and tool-layer changes.

| Component | p50 now | p95 | p99 | ops/sec | p50 baseline | Change |
|---|---:|---:|---:|---:|---:|---|
| Intent routing (regex tier) | 170 µs | 1.66 ms | 2.34 ms | 2,273 | 1,497 µs | **~9x faster** |
| Permission check | 1.5 µs | 2.7 µs | 3.1 µs | 605,321 | 1.2 µs | same |
| Registry execute (gated, stub tool) | 48 µs | 113 µs | 176 µs | 16,175 | 8 µs | **slower** (+40 µs) |
| Scoped registry execute | 45 µs | 115 µs | 165 µs | 16,704 | 9 µs | **slower** (+36 µs) |
| Run-budget charge | 8 µs | 16 µs | 26 µs | 101,296 | 5.5 µs | slower (+3 µs) |
| Tool loop: 3 tool calls + answer | 330 µs | 595 µs | 702 µs | 2,694 | 113 µs | **slower** (~2.9x) |
| Plan decompose + sanitise (12 steps) | 212 µs | 377 µs | 528 µs | 4,218 | 167 µs | slower (+27%) |
| Plan execution (5 handler steps) | 1.33 ms | 2.63 ms | 3.54 ms | 634 | 0.83 ms | **slower** (+59%) |
| Memory: remember fact (4 stores) | 439 µs | 854 µs | 1.10 ms | 1,942 | 342 µs | slower (+28%) |
| Memory: forget (all stores) | 403 µs | 737 µs | 972 µs | 2,014 | 218 µs | slower (~1.9x) |
| Usage tracking per LLM call (memory) | 8 µs | 17 µs | 33 µs | 88,377 | 7.6 µs | same |
| Usage tracking per LLM call (+ SQLite row) | 112 µs | 258 µs | 499 µs | 4,683 | 102 µs | slightly slower |

Cold import (fresh interpreter): `core.router` 235 ms · `core.agent_executor` 128 ms · `core.specialists` 94 ms · `core.goal_planner` 98 ms.

**Reading these numbers honestly**

- Several paths are **not** within the 10% budget that was set for this work. The main causes: tools now run in a worker pool so timeouts are enforced (a thread hand-off per call instead of calling inline), memory writes scrub secrets and update a search index, and the permission/capability gate does more checks. Everything stayed in the tens of microseconds to ~1 ms range, which is tiny next to a model call (seconds) or a tool that touches the disk or network. It was accepted, not optimised away. The obvious next step if it matters: let known-fast read-only tools skip the worker pool.
- Run-to-run variance is visible (memory forget measured 224 µs in another run the same hour); treat all latencies as order-of-magnitude.
- The routing median in `python -m evals.run` (~0.5 ms) is higher than the 170 µs in the bench because it includes the first-call costs of a cold router.

### Start-up (measured separately, not part of `evals.bench`)

| Step | Before | After |
|---|---:|---:|
| `import core.brain` | ~16 s | ~0.35 s |
| `import core.orchestrator` | ~5.4 s | ~0.8 s |
| Constructing `FlexieOrchestrator()` | ~9.1 s | ~1.1 s |
| **Import + construct** | **~14.5 s** | **~1.9 s** |

How: both Gemini SDKs and the other model SDKs are imported only when a provider is used; `pygame`, `pyautogui`, `pytesseract`/`pandas` and `playwright` load on first use (`utils/lazy.py`); the vector store (chromadb import + Ollama probe, ~6 s) and the model clients are built in background threads; Tesseract is checked on first OCR. Trade-off: the first model call right after launch may wait for those threads (bounded at 30 s; ~6 s when a command is issued immediately in a test). Voice, microphone calibration and UI start-up in `main.py` were not timed.

### Earlier before/after (memory writes, unchanged)

| Item | Before | After |
|---|---:|---:|
| Memory write (`MemoryManager.remember`) | 20.7 ms | 0.15 ms |
| Memory write (`MemorySystem.set_preference`) | 14.1 ms | 0.09 ms |
| Memory write (`SelfAwareness.learn_fact`) | 13.7 ms | 0.10 ms |
| `MemoryEngine.add_chat` | 15.4 ms | 0.25 ms |

Cause: a new SQLite connection per write (journal files created/deleted each time on Windows). Fix: one shared WAL connection per database with real transactions (`utils/sqlite_util.py`). Trade-off: WAL + `synchronous=NORMAL` can lose only the last few commits on OS crash / power loss.

## 3. What was fixed (summary; details in `docs/FIX_CHECKLIST.md`)

**Security**
- `/health` no longer leaks the API token (issued only to allowlisted origins / `FLEXIE_EXTENSION_IDS` / `FLEXIE_EXTRA_ORIGINS`); explicit CORS allowlist; HTTP 421 for foreign Host headers; WebSocket Origin/Host checks; UDP datagrams signed in both directions.
- Permissions fail closed in `ToolRegistry.execute`; approvals have an id and a TTL and are single-use and scoped to the running action; the capability policy denies undeclared capabilities.
- Danger detection runs per sentence/clause; confirmation accepts only short pure approvals; the command filter normalises Unicode and matches restricted words as whole words.
- File jail (writes and secret reads), terminal subcommand/flag policy, MCP defaults to *confirm* with size-capped, untrusted-wrapped output, plugin allow-list, mail send/reply wait for explicit approval.
- Prompt-injection boundary: tool output is untrusted data; after web/email/MCP content enters a turn, effectful tools need approval until the next user turn. Model-generated plans are untrusted (unknown tools dropped, types coerced, steps ≤ 8, timeouts capped).

**Correctness / behaviour**
- Planner output reaches `AgentExecutor` as a typed `TaskGraph`; one `_resolve_route`; the controller forwards `is_subcommand`/`silent`/`depth`.
- Memory: single remember/forget path across all stores, secrets scrubbed, TTL/caps/pruning, structured values round-trip, ranked search.
- LLM layer: provider failures never become answers (web-search fallback text is rejected for code, JSON and image requests), Groq sibling models and Gemini model fallback, per-model timeouts, failed calls recorded separately, half-open circuit breaker.
- Screen requests go only to vision-capable providers and fall back to OCR text with an honest message; screenshots report where they were saved.
- Project builder: a model failure message is never written into a source file; empty/stub files are rejected; the static verifier checks linked files; a build that produced nothing leaves no folder; tests no longer write into `Downloads`.
- Router: fuzzy typo correction no longer rewrites real short words; misroutes found in live logs fixed ("wrong …" no longer undoes, "check my screen", "open chrome and search for X", dismissals).
- New: live self model, image downloader, vision-mode launcher (see `docs/README_FEATURES.md`).

Bugs found *by running real text commands* (not by unit tests): a patch of mine that deleted a helper and crashed every model call; a 7 s model timeout that Gemini rejects (minimum 10 s); a retired Gemini model name; a project file containing a web-search sentence marked as a successful build; test runs creating ~150 empty folders in `Downloads`; a `\b` regex corrupted into a backspace character by shell-escaping (caught three times by tests/behaviour).

## 4. Not done / not measured (read this before trusting the numbers)

- **No real-model measurement.** Plan quality, tool selection and task success with a live LLM were not run; all agent evals use a fake model. The Brain JSON tool protocol is untested against a real (especially small local) model.
- **Not exercised live:** voice recognition and barge-in, voice approval, the browser extension, desktop/browser automation end to end, real IMAP/Docker/MCP servers, Gemini vision (the service answered HTTP 503 "high demand" during testing), the GitHub Actions run. Text commands through the real orchestrator were tried by hand.
- **End-to-end latency of a spoken command** (mic → recognition → model → speech) was not measured; only start-up and the deterministic stack were.
- **Per-command tokens/cost** are recorded by `core/telemetry` with real provider usage where returned, but this benchmark uses a fake model, so only the tracking overhead (~8 µs in memory, ~112 µs with the SQLite row) is measured here. No head-to-head against OpenJarvis was run.
- **Still open:** orchestrator is ~1,530 lines (target < 600) and has unproven races (clarification prompt listens in the action worker; clarification reply can re-queue itself; the 90 s watchdog does not stop the hung worker; unbounded speech queue); stores still sit side by side behind `MemoryFacade`; skill/MCP trust tiers; provider hedging; unused `supervisor/` and `runtime/` modules; signed installer / rollback.
- Regex/wording-based safety (`DangerGate`, permission classifier) still judges user phrasing for handler-routed steps; typed tool permissions are the stronger layer.
- Loop-guard thresholds (20 steps / 300 s / 3 repeats) are untuned defaults.
- Benchmark is one run on one machine; treat latencies as order-of-magnitude, not guarantees.

## 5. Configuration added during this work

| Variable | Purpose | Default |
|---|---|---|
| `FLEXIE_EXTENSION_IDS` | Extension IDs trusted to receive the API token (**required for the browser extension**) | none |
| `FLEXIE_EXTRA_ORIGINS` | Extra `http(s)` origins that may receive the API token (no wildcards) | none |
| `FLEXIE_USER_NAME` | Name used in greetings/prompts | OS username |
| `FLEXIE_DATA_DIR` | Where memory databases live | project folder |
| `FLEXIE_ALLOW_UNSANDBOXED_EXEC` | Allow `python.exec` outside the sandbox | off |
| `FLEXIE_RUN_MAX_STEPS` / `_SECONDS` / `_REPEATS` | Run budget / loop guard | 20 / 300 / 3 |
| `FLEXIE_ALLOW_UNSIGNED_UI` | Accept unsigned UI-bound UDP datagrams (migration aid) | off |
| `FLEXIE_MAIL_APPROVAL_WAIT` | Seconds the mail send/reply endpoints wait for an approval | 60 |
| `FLEXIE_CLIPBOARD_MONITOR` | Opt in to clipboard history | off |
| `FLEXIE_CODE_OUTPUT_DIR` | Where build jobs create workspaces | `~/Downloads` |
| `GROQ_FALLBACK_MODELS` | Groq sibling models tried when the main one is rate-limited | `openai/gpt-oss-120b,qwen/qwen3.8-27b` |
| `FLEXIE_PRICING_FILE` | Real per-model prices for cost estimates | built-in blended rates |

## 6. Token and cost telemetry

Every successful LLM call is recorded with provider, model, prompt/completion tokens (exact when the provider returns usage, else a flagged ~4 chars/token estimate), estimated cost and latency, attributed to the user command in flight; failed calls are stored too but excluded from token/cost totals and counted in a failure rate. Read it with `python -m core.telemetry.report` or `GET /api/flexie/usage`. Cost is an estimate (blended per-provider rates; set `FLEXIE_PRICING_FILE` for real prices). Data older than 30 days is pruned (`FLEXIE_RETENTION_DAYS`). Full write-up: `FINAL_REPORT.html` (written earlier in the project; its test and eval counts predate this update).
