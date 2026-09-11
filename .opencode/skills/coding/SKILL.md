# Flexie Coding Skill — Autonomous Code Workflow

Use this skill whenever the user asks to code, build, fix, patch, test, or generate a project.

## Trigger
Intents: `sdd_build`, `dev_build`, `code_gen`, `local_code_search`, `bug_hunter`, `test_generator`, `dev_explain`, `repo_analyzer`
Natural language: "build me a...", "create a project", "fix this bug", "generate code", "search my code", "audit repo"

## Workflow (Observe → Act → Verify)

1. **Observe**
   - `file.read` or `code.search` to inspect existing files
   - `git.status` / `git.diff` to check current changes
   - `project.explain` for architecture overview (writes `flexie_project_explanation.md`)
   - Use `core/goal_planner.py:163 GoalPlanner.decompose()` to break complex request into `TaskGraph`

2. **Act** (via ToolRegistry `core/tool_registry.py:105`)
   - `file.write` - create new files (auto creates dirs)
   - `file.patch` - surgical edit (exact snippet replacement, fails if ambiguous)
   - `terminal.run` - shell commands (safety-guarded via `core/safety.py:6`)
   - `python.exec` - run python in `sandbox/executor.py:15 SandboxExecutor` (Docker if available, else host with `allow_host_fallback=True`)

3. **Verify**
   - `file.read` to confirm patch applied
   - `python.exec` or `terminal.run` to execute
   - `test.run` to run `pytest tests/ -q` (must pass before commit)
   - `AgentExecutor._verify()` `core/agent_executor.py:188` checks `FILE_EXISTS` / `TESTS_PASS`

4. **Retry / Self-Correct**
   - On `ActionResult.fail` `core/action_result.py:17`, feed `stderr` to `core/brain.py:157 Brain.ask()` for fix
   - Increment `TaskStep.retry_count` `core/goal_planner.py:59` up to `max_retries=2`
   - Log to `core/memory_manager.py:31 MemoryManager` category `TASKS` for future learning

5. **Report**
   - Summarize via `speak_stream` `core/orchestrator.py:305`
   - Optionally `git.commit` if tests pass (requires `SENSITIVE` permission)

## Examples

**Build new project:**
```
User: "build me a todo app with python"
→ GoalPlanner decomposes → sdd/engineer.py:216 autonomous_build(autonomous=True)
→ file.write for each planned file → python.exec verify → test.run
```

**Fix bug:**
```
User: "fix the login bug in handlers/auth.py"
→ code.search("login") → file.read("handlers/auth.py")
→ sdd/engineer.py:88 generate_patch() → file.patch()
→ test.run → if fail, brain.ask for corrected patch
```

**Search & Explain:**
```
User: "explain this project"
→ project.explain → writes flexie_project_explanation.md
User: "search my code for router"
→ code.search("router") → returns handlers/router.py:201 etc
```

## Safety

- `core/permission_system.py:26` enforces READ_ONLY → DANGEROUS levels
- `core/safety.py:6 SafetyGuard` blocks `rm -rf`, `del /s`, `format`
- `sandbox/executor.py:15` refuses host execution unless `allow_host_fallback=True` explicitly set
- All file writes are verified via `FILE_EXISTS` before marking step COMPLETED

## Integration Points

- `core/orchestrator.py:152` → `ToolRegistry` + `AgentExecutor` (observe-act-verify)
- `core/dag_planner.py:1` → 4-thread parallel for independent file writes
- `sdd/engineer.py:8` → PRD → spec → task graph → patch generation
- `utils/config.py:76` → `FOLDER_SHORTCUTS` for desktop/downloads resolution
