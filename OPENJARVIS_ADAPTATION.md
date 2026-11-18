# OpenJarvis → Flexie Adaptation Plan

> Comparison baseline: OpenJarvis (`open-jarvis/OpenJarvis`, Apache-2.0, Stanford Hazy Research) vs Flexie 2.0.
> Flexie audit performed on this repo: 38,567 Python LOC, 36 test files, 627 tests collected, 979 ruff findings.
> OpenJarvis is a **framework**; Flexie is a **Windows product**. Adopt the framework layer, not its research surface.

---

## 0. TL;DR

Flexie already has more end-user capability than OpenJarvis: voice, desktop control, browser automation, 90 intents, dev jobs, a browser extension, and a real safety stack. What Flexie lacks is the layer that makes an agent system **improvable**:

1. **Evaluation** — you cannot prove a change helped.
2. **Traces/telemetry** — you cannot see where a task failed or what it cost.
3. **Typed agent primitives** — specialists are keyword routers, not tool-using agents.
4. **Skills** — every new capability requires a new handler and router entry.
5. **Local-first inference** — the default chain starts at Groq, not Ollama.

Do these five before importing anything else.

---

## 1. Current Flexie baseline (measured)

| Signal | Result | Reading |
|---|---|---|
| Python LOC (source only) | 38,567 | Large prototype; `core/` is 17,799 |
| Test files / collected | 36 / 627 | README's "600+ across 35+" is accurate |
| Full-suite result | 23 failed / 627 | ~96.3% pass in one run |
| Handler failures | 17 in `tests/test_handlers.py` | **Pass individually** — order-dependent state/monkeypatch leakage, not 17 broken features |
| Router failure | `"check gmail"` → `mail_check`, test expects `gmail` | Intent precedence mismatch |
| Docs-drift test | `test_readme_counts_models_ports` expects "480 test cases across 18 test files" | Stale assertion vs current README |
| Ruff findings | 979 (315 W293, 120 E701, 83 E702, 84 I001) | Mostly cosmetic; includes 17 unused imports, 1 bare except, 1 F821, duplicate dict keys |
| `except Exception` sites | 567 | Broad swallowing; many are intentional but hide failures |
| TODO/FIXME/HACK | 293 | Normal for this size, but signals unfinished paths |
| Files > 800 LOC | 9 | `router.py` 1,346; `orchestrator.py` 1,302 |
| License | **No LICENSE file** | Blocks open-source distribution |
| Telemetry | 34-line JSONL latency logger | No tokens, cost, traces, or outcomes |

**Confirmed integration bug:** `core/agent_loop.py` calls `registry.get_tool(...)` and `tool.execute(...)`, but `core/tool_registry.py` exposes `get(...)` and `ToolSpec.execute_fn`. Tool calls therefore degrade to "not available in registry."

**Hardcoded dependency bug:** `core/agent_loop.py` hardcodes Ollama model `deepseek-r1` regardless of `ModelHub` selection.

---

## 2. Add directly from OpenJarvis

These are **specs, schemas, and conventions** you can implement without importing the package. If you copy actual source files, follow the Apache-2.0 notice requirement (see §7).

### 2.1 Persona files — highest value per line of code

| Item | OpenJarvis behavior | Flexie implementation |
|---|---|---|
| `SOUL.md` | Tone, length, what to push back on | `data/persona/SOUL.md` |
| `MEMORY.md` | Durable facts and preferences | `data/persona/MEMORY.md` |
| `USER.md` | Role, team, context | `data/persona/USER.md` |
| Loader | Read once per conversation, inject after system template, cap chars per section, skip missing files | `core/persona.py` |
| Named personas | `~/.openjarvis/personas/<name>/*.md`, `--persona work|none` | Optional `FLEXIE_PERSONA` env var |

Flexie already writes `data/MEMORY.md` and `workspace/MEMORY.md`. Formalize the convention instead of inventing a new one. Add a `memory_manage` tool so the agent can append facts mid-conversation.

**Acceptance:** deleting a line from `SOUL.md` changes the next conversation's behavior; no restart required.

### 2.2 Telemetry record schema

Adopt these fields verbatim in a `TelemetryRecord` dataclass:

`timestamp, model_id, engine, agent, prompt_tokens, completion_tokens, total_tokens, latency_seconds, ttft, cost_usd, energy_joules, power_watts, metadata`

Flexie already has `TokenTracker.PRICE_PER_1K` in `core/model_hub.py`; reuse it for `cost_usd`. Energy can start as `None`, then add GPU/CPU sampling later.

### 2.3 Trace + TraceStep schema

This is the bridge between telemetry and learning.

`Trace`: `trace_id, query, agent, model, engine, steps[], result, outcome, feedback, started_at, ended_at, total_tokens, total_latency_seconds, metadata`

`TraceStep`: `step_type, timestamp, duration_seconds, input, output, metadata`

`StepType`: `route`, `retrieve`, `generate`, `tool_call`, `respond`

Flexie already has an `EventBus` (`core/event_bus/bus.py`). Subscribe a collector to it rather than instrumenting every handler by hand.

### 2.4 Evaluation vs benchmark split

OpenJarvis separates:
- **Evals** = correctness on a fixed task set (`jarvis eval`).
- **Bench** = engine speed/throughput (`jarvis bench`).

Flexie needs only the first. Adopt the JSONL result shape:

```json
{"task_id": "route-001", "query": "check gmail", "expected": "gmail", "predicted": "mail_check", "correct": false, "latency_ms": 3.2, "tokens": 0, "cost_usd": 0.0}
```

A 50–100 task set drawn from your 90 intents would have caught the current router regression and the docs drift.

### 2.5 Agent primitives

Adopt these interfaces (names matter less than the contracts):

```python
class BaseAgent(ABC):
    agent_id: str
    accepts_tools: bool = False

    @abstractmethod
    def run(self, input: str, context: AgentContext | None = None) -> AgentResult: ...

@dataclass
class AgentContext:
    conversation: list[dict]
    tools: list[str]
    memory_results: list[Any]
    metadata: dict[str, Any]

@dataclass
class AgentResult:
    content: str
    tool_results: list[ToolResult]
    turns: int
    metadata: dict[str, Any]
```

`ToolUsingAgent` adds `accepts_tools = True`, a `max_turns` loop, and a `ToolExecutor`. Start with three agents: `simple`, `orchestrator`, `react`. Map Flexie's roles to them later.

### 2.6 Inference engine interface

One interface, many providers:

```python
class InferenceEngine(Protocol):
    engine_id: str
    def generate(self, messages, tools=None, **params) -> EngineResponse: ...
    def capabilities(self) -> EngineCapabilities: ...
```

Registry keys: `ollama`, `groq`, `openai`, `gemini`, `anthropic`, `deepseek`, `mistral`. This replaces the split between `Brain`'s fallback chain and `ModelHub`'s task mappings.

### 2.7 Capability vocabulary

Use OpenJarvis's names for tool/skill declarations:

- `network:fetch`
- `filesystem:read`
- `filesystem:write`
- `shell:execute`
- `memory:read`
- `memory:write`
- `engine:inference`
- `network:listen`

Map these onto your existing `PermissionLevel` (`READ_ONLY` → `SAFE_ACTION` → `USER_CONFIRMATION` → `SENSITIVE` → `DANGEROUS`).

### 2.8 Skill format

Start with **instruction-only** skills (no code execution):

```markdown
---
name: code-explainer
description: Explain code in plain language with examples
license: MIT
metadata:
  openjarvis:
    version: "0.1.0"
    tags: [coding, explanation]
---
1. Identify the language.
2. Break the code into sections.
3. Explain each section, then give a one-sentence summary.
```

Later add `skill.toml` pipelines with `tool_name`, `arguments_template`, and `output_key` steps. This is the agentskills.io open standard, so third-party skills are portable.

### 2.9 Trust tiers

Adopt the four tiers for anything installed from outside:

| Tier | Source | Verification |
|---|---|---|
| Bundled | Ships with Flexie | Implicit trust |
| Indexed | Official index | SHA256 + signature |
| Unreviewed | Arbitrary GitHub URL | SHA256 + sandbox warning |
| Workspace | Local `./skills/` | Trusted user code |

### 2.10 CLI and API conventions

Follow the shapes users already know:

```bash
flexie eval list
flexie eval run -b routing -n 100
flexie telemetry stats
flexie telemetry export -f csv -o metrics.csv
flexie skill list
flexie skill install github:user/repo/path --url https://github.com/user/repo
flexie skill run research-and-summarize -a query="..."
```

For the API, expose an OpenAI-compatible surface (`POST /v1/chat/completions` + SSE) in addition to `/command`. `core/model_hub.py` already has an OpenAI bridge; promote it to the main server rather than maintaining two API shapes.

---

## 3. Update in your code

| File | Change | Acceptance check |
|---|---|---|
| `core/telemetry.py` | Replace 34-line logger with `TelemetryStore` (SQLite) + `TelemetryAggregator`; keep a thin `Telemetry` shim | `flexie telemetry stats` returns calls, tokens, cost, p50/p95 latency |
| `core/event_bus/bus.py` | Add typed events: `INFERENCE_START/END`, `TOOL_CALL_START/END`, `MEMORY_RETRIEVE`, `TRACE_COMPLETE` | A trace is written for a single command end-to-end |
| `core/model_hub.py` + `core/brain.py` | Collapse into `InferenceEngine` registry; remove hardcoded model names (`llama3.2:1b`, `qwen2.5-coder:7b` etc. → config) | Switching `FLEXIE_ENGINE=ollama` routes every task locally |
| `core/agent_loop.py` | Fix `get_tool` → `get`, `execute` → `execute_fn`; remove hardcoded `deepseek-r1`; parse tool calls structurally (JSON), not substring matching | A tool call actually executes and returns a result |
| `core/specialists.py` | Make each specialist a `ToolUsingAgent` with a scoped `ToolRegistry` and `max_turns`; stop returning `brain.ask()` after one call | Coder agent can read, write, test, and retry |
| `core/tool_registry.py` | Add `capabilities: list[str]`, `tool_call_id` in results, `get_tool()` alias, and JSON-schema export for function calling | MCP tools and native tools share one execution path |
| `core/router.py` | Keep the deterministic fast path, but move open-ended requests to the skill catalog; fix duplicate `TYPO_MAP` keys (`F601`); resolve `check gmail` → `mail_check` vs `gmail` | `pytest tests/test_router.py` passes |
| Memory modules | Consolidate `memory_manager.py`, `vector_store.py`, `engines/memory.py`, `engines/long_term_memory.py` behind one `MemoryBackend` with `retrieve(query, k)` and `remember(entry)` | One API; retrieval returns `memory_results` in `AgentContext` |
| `core/orchestrator.py` | Extract command dispatch, streaming, and memory extraction into focused modules; target < 600 LOC | No behavior change; tests pass |
| `interface/api_server.py` | Add `/v1/chat/completions` + SSE; reuse bearer token auth | An OpenAI client can talk to Flexie |
| `tests/` | Fix test-order pollution (module-level monkeypatch/sys.modules state); add eval regression tasks | Full suite passes in one run, in any order |
| `README.md` / `README_FEATURES.md` | Update counts (627 tests / 36 files), remove stale claims, add License section | `test_readme_counts_models_ports` passes |
| Repo root | Add `LICENSE`, `NOTICE`, `CONTRIBUTING.md` | GitHub shows a license |

### Confirmed defects to fix while in there

1. `core/agent_loop.py` registry API mismatch (tool execution never works through `ToolRegistry`).
2. `core/agent_loop.py` hardcoded `deepseek-r1`.
3. `core/router.py` duplicate dictionary keys flagged by `F601`.
4. `engines/system.py` has an `F821` undefined-name finding — run `ruff check --select F821` and fix.
5. 17 handler tests depend on execution order — likely leaked `monkeypatch`/module stubs.

---

## 4. Create (new files and directories)

```text
evals/
  tasks/routing.jsonl           # command -> expected_intent
  tasks/tools.jsonl             # task -> must_call tools + success check
  tasks/jobs.jsonl              # build job -> acceptance criteria
  run.py                        # accuracy, pass@1, latency, cost
  configs/local.toml            # local models only
core/telemetry/
  record.py                     # TelemetryRecord
  store.py                      # SQLite append-only store
  aggregator.py                 # summary/per_model/per_engine
core/traces/
  collector.py                  # EventBus -> Trace
  store.py                      # traces + trace_steps
  analyzer.py                   # per-route/per-tool stats
core/agents/
  base.py                       # BaseAgent, AgentContext, AgentResult
  registry.py                   # name -> agent
  tool_using.py                 # ToolUsingAgent loop
core/inference/
  base.py                       # InferenceEngine protocol
  registry.py                   # provider registry
  hardware.py                   # GPU/VRAM detection + model recommendation
core/skills/
  loader.py                     # SKILL.md + skill.toml parser
  catalog.py                    # XML catalog for system prompt
  executor.py                   # pipeline steps (phase 2)
skills/
  code-explainer/SKILL.md
  research-and-summarize/SKILL.md
data/persona/
  SOUL.md
  MEMORY.md
  USER.md
LICENSE                         # Apache-2.0 or MIT
NOTICE                          # if any OpenJarvis code is copied
CONTRIBUTING.md
```

---

## 5. Build order and effort

| Phase | Work | Effort | Done when |
|---|---|---|---|
| **P0** | Eval harness (routing + tools, 50–100 tasks); fix 23 failing tests; add LICENSE | 2–3 days | `flexie eval run` reports accuracy; full suite green |
| **P1** | Telemetry store + trace collector wired to `EventBus` | 3–4 days | One command produces one trace with steps, tokens, cost, latency |
| **P2** | `BaseAgent`/`ToolUsingAgent`; fix `agent_loop.py`; rewrite specialists | 4–5 days | Coder agent runs a real multi-turn tool loop |
| **P3** | Persona files + skill catalog (instruction-only) | 2–3 days | New capability added as `SKILL.md` with no router change |
| **P4** | `InferenceEngine` registry + local-first default + hardware detection | 3–4 days | `FLEXIE_ENGINE=ollama` works for every task type |
| **P5** | Capability gating for MCP/skills; trust tiers; skill pipelines | 1–2 weeks | External skill cannot exceed declared capabilities |

P0 is non-negotiable. P1 unlocks every later measurement. P4 is what makes the "local" claim true.

---

## 6. Do not copy

- **40 benchmarks and 10 engine backends.** Flexie needs 5–10 tasks that mirror real usage.
- **The Rust extension.** Premature for a PyInstaller Windows app.
- **LLM-guided spec search / DSPy / GEPA.** These require a benchmark and trace corpus Flexie does not have yet. Revisit after P0–P2.
- **Full desktop app packaging.** Flexie already ships a PyInstaller build.
- **OpenJarvis's module tree wholesale.** Its five primitives are the value; its file layout assumes a research monorepo.

---

## 7. License note

OpenJarvis is **Apache-2.0**. If you copy source files:

1. Retain copyright and license notices.
2. Add a root `NOTICE` stating which files are derived from OpenJarvis.
3. State significant changes in those files.

If you reimplement the ideas, schemas, and interfaces (recommended), no license obligation applies, but attribution in the README is good practice.

Flexie is licensed **MIT** (see `LICENSE`). The AGPL `PyMuPDF` dependency has been replaced with `pypdf` (BSD-3-Clause), so the bundled binary no longer pulls copyleft obligations into the combined work.

---

## 8. Mapping table

| OpenJarvis concept | Flexie today | Action |
|---|---|---|
| `BaseAgent` / `AgentRegistry` | `core/specialists.py` keyword router | Rebuild as registered tool-using agents |
| `InferenceEngine` registry | `Brain` chain + `ModelHub` task map | Unify behind one interface |
| `TelemetryStore` / `TraceStore` | `core/telemetry.py` latency log | Replace with SQLite stores |
| `TraceCollector` | `EventBus` exists, unused for traces | Subscribe collector |
| `openjarvis.evals` | none | Create `evals/` |
| `openjarvis.bench` | none | Optional later |
| `SOUL.md` / `MEMORY.md` / `USER.md` | ad-hoc `MEMORY.md` files | Formalize loader |
| `SKILL.md` / `skill.toml` | 45 handlers + 90 router intents | Add skill catalog; migrate reusable flows |
| Capability declarations | `PermissionLevel` only | Add capability field + validation |
| Trust tiers | none | Add for MCP/skills |
| OpenAI-compatible API | `ModelHub` bridge + `/command` | Promote to main API |
| Hardware detection | none | Add for Ollama model choice |

---

## 9. Success metric

After P0–P2, Flexie should be able to answer, for any change:

> "Routing accuracy went from X% to Y%; p95 latency changed by Z ms; cost per command changed by $W; the failing trace shows the tool call at step 4."

Until it can answer that, further feature work is guesswork.

---

## 10. Implementation status (Nov 9, 2026)

| Phase | Status | Evidence |
|---|---|---|
| P0 — eval harness, tests, license | **Done** | 45/45 routing tasks pass; full suite reports 650 passed; MIT `LICENSE` added; eval gate wired into CI |
| P1 — telemetry + traces | **Done** | `core/telemetry/` (record, SQLite store), `core/traces/` (trace, store, EventBus collector, analyzer) |
| P2 — agent primitives | **Done (Nov 18)** | Specialists are scoped `ToolUsingAgent`s over a `ScopedToolRegistry` (hard tool boundary), with step budget + loop guard, approval path, `delegate` tool for the lead, and word-boundary routing. See §11. |
| P3 — persona + skills | **Done** | `core/persona.py`, `data/persona/*.md`, `core/skills/`, two starter `SKILL.md` files, injected into the Brain prompt |
| P4 — inference engine registry / local-first default | **Done** | `core/inference/` (`InferenceEngine`, `EngineRegistry`, `OllamaEngine` via `/api/chat`, `CallableEngine`, hardware detection). `Brain` tries Ollama before cloud when `FLEXIE_LOCAL_FIRST=1`; `FLEXIE_ENGINE` selects an engine. |
| P5 — capability gating / trust tiers | **Partial** | Capability gating + permission enforcement in `ToolRegistry.execute`; untrusted-content taint (web/email/MCP) gates effectful tools (§11). Trust tiers and per-skill capability sets are still open. |

Fixed during P0: `engines/system.py` undefined `logging`, `agent_loop` `get_tool`/`execute` mismatch, duplicate `TYPO_MAP` keys, order-dependent handler tests, stale docs-drift assertions, and the `gmail` routing mismatch.

Also added in this pass: live `TraceCollector` wrapping of `handle_command`, an OpenAI-compatible `POST /v1/chat/completions` endpoint, `FLEXIE_LOCAL_FIRST` / `FLEXIE_ENGINE` config, and CI routing-eval gating.

### Remaining gap to 9/10

Honest re-rating after these changes: **~7.7/10** (product usefulness ~7.5, engineering ~8.0). The architecture and measurement gaps are largely closed; the remaining points are not feature add-ons:

1. **Portability (hard blocker).** Flexie is still Windows-native: `engines/system.py` imports `pycaw`/`comtypes` at module scope, and the desktop engines assume Win32 APIs. To approach 9/10, move those imports behind platform guards and make the orchestrator degrade on macOS/Linux. OpenJarvis gets its score partly by running everywhere.
2. **Trust tiers and skill sandboxing.** Capability gating now exists at the tool boundary, but skills do not yet declare or receive a restricted capability set, and there are no trust tiers for third-party MCP servers.
3. **Benchmark breadth.** 45 routing tasks is a start, not a benchmark. Add tool-use and end-to-end task evals (target 150+), with per-category accuracy and latency thresholds in CI.
4. **CI evidence.** The eval gate is now in `ci.yml`, but it has not yet run on GitHub. A green Actions run is the evidence a 9/10 claim needs.
5. **Packaging and recovery.** Signed installer, pinned dependencies, upgrade/rollback path, and a reproducible offline install are still missing.

---

## 11. Update — Nov 18, 2026

Done since §10 (all covered by tests and by the CI-gated agent evals, `python -m evals.agent_run`):

| Area | Change |
|---|---|
| Permissions | `ToolRegistry.execute` fails closed through a `PermissionSystem` gate; approvals are single-use (consumed after the approved action); `AgentExecutor` no longer "logs and continues" on denial; voice approval is asked directly instead of deadlocking the action thread |
| API | `/health` no longer leaks the bearer token (issued only to allowlisted origins / `FLEXIE_EXTENSION_IDS`); CORS is an explicit allowlist |
| Sandbox | `use_sandbox` removed from `python.exec`; unsandboxed execution is operator policy (`FLEXIE_ALLOW_UNSANDBOXED_EXEC`) |
| Execution path | GoalPlanner output now reaches `AgentExecutor` as a typed `TaskGraph` (it was silently discarded by a `s.command` AttributeError). Model plans are treated as untrusted: unknown tools dropped, types coerced, steps/timeouts capped, risk level never taken from the model |
| Harness | `RunBudget` (step / time / repeat caps) on plan execution and specialist loops; agent-level evals (39 tasks) gate CI; `python -m evals.bench` benchmarks the deterministic stack |
| Specialists (P2) | Scoped registries, real tool loop over `Brain`, approvals, delegation, whole-word routing |
| Prompt injection | Tool output is fed back as untrusted data; after untrusted content (web/email/MCP) enters a turn, effectful tools (click/fill/open) need approval until the next user turn |
| Memory | `MemoryFacade` = single remember/forget path across all stores (forget previously left copies behind); wiki rewrite debounced; DB paths anchored to the project; shared WAL connections cut memory writes from ~14–20 ms to ~0.1 ms |
| Routing | One `_resolve_route`; deterministic router beats learned routes; router runs once per command; authoritative overrides skip the planner |
| Portability | `engines/system.py` imports without `pycaw`/`comtypes`/`pyautogui` (audio/desktop controls degrade) |

Still open: orchestrator break-up (<600 LOC; currently ~1,400), one `MemoryBackend` (the stores still exist side by side), skill/MCP trust tiers and per-skill capability sets, native-vs-MCP shared execution path, per-command token/cost telemetry, signed installer and rollback, and a green GitHub Actions run as evidence. Measured results: see `BENCHMARK_REPORT.md`.
