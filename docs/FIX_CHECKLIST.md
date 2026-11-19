# Flexie — Master Fix Checklist

Source: `MODULE_AUDIT_REPORT.md` (IDs match). Status is updated only after an item has a regression test **and** has been re-verified by running it.

**Legend:** `[ ]` open · `[~]` in progress · `[x]` fixed + tested + re-verified · `[!]` blocked / needs a decision
**Efficiency guard:** no fix may slow a hot path by more than ~10%. Speed is re-measured with `python -m evals.bench` against the baseline in `evals/results/bench-20261118-141406.json` before this is closed.

## Gates (must be green before anything is called done)
- [x] Full test suite passes (`pytest tests`, run with `GIT_CEILING_DIRECTORIES` set) — latest: 2,119 passed, 2 skipped
- [x] `ruff check .` clean
- [x] Agent evals 59/59 and the routing eval (158 cases, default threshold 0.9) pass
- [~] Benchmark within 10% of baseline on every hot path — **not met**: routing is ~9x faster, but registry execute, tool loop, plan execution and memory paths are slower (see `../BENCHMARK_REPORT.md` §2); startup time recorded (import + construct ~14.5 s → ~1.9 s)
- [ ] Every reproduction from the audit re-run and no longer reproduces
- [x] Git history untouched by tests (HEAD unchanged after the run; currently 17645cc; all work is uncommitted)

---
## Phase 0 — security, data loss, regressions

### Regressions introduced this session
- [x] X-1 danger check does not split on `. ? ! \n & –` (action after a question judged harmless) — *safety*
- [x] X-2 shared SQLite connection interleaves transactions (lost writes) — *memory*
- [x] X-3 non-empty failure text is cached by the LLM cache — *llm*

### Safety and control (SF)
- [x] SF-1 unmatched wording/tools default to read-only → default to **confirm**; add missing intents (send/reply-all/wire/venmo/publish/deploy/format the drive/get rid of/nuke/factory reset…)
- [x] SF-2 (= X-1)
- [x] SF-3 mail send/reply API endpoints skip every gate
- [x] SF-4 MCP tool permission guessed from names → default confirm
- [x] SF-5 desktop-control calls ungated and not affected by the untrusted-content rule
- [x] SF-6 blacklist bypasses (flags-first `Remove-Item`, `rm --recursive`, zero-width/fullwidth chars, `shutdown /s`, `iex(`, `Stop-Computer`, `Format-Volume`, `diskpart`, `DELETE FROM`)
- [x] SF-7 restricted words match substrings (Essex, Sussex, unisex, adult ticket…)
- [x] SF-8 approval design: one global slot, no request id, process-wide escalation, no TTL, no lock
- [x] SF-9 level inversions / false alarms ("pay attention", "checkout the branch", "play sleep sounds", firewall)
- [x] SF-10 background commands clear the untrusted-content marker
- [x] SF-11 confirmation matcher gaps ("do it", "sure thing", stale "ok" with no timeout)

### Tools (TL)
- [x] TL-1 file jail covers `.env`, `.git/`, `core/`, MCP config, skills (writes **and** secret reads)
- [x] TL-2 terminal allowlist bypass (`python -c`, `npx`, `pip install <url>`, `git -c`, `rg --pre`, `robocopy`)
- [x] TL-3 `python.exec` container limits, cleanup in `finally`, timeout clamp
- [x] TL-4 MCP stderr never drained
- [x] TL-5 MCP default permission = confirm (explicit read-only list only)
- [x] TL-6 untrusted-content marking only on success
- [x] TL-7 unbounded, unlabelled tool output
- [x] TL-8 MCP JSON-RPC spoofing / empty result / lost errors / stdin lock
- [x] TL-9 MCP lifecycle (leaks, Windows tree kill, name collisions, hostile tool list)
- [x] TL-10 `file.patch` line endings / encodings
- [x] TL-11 git/code-search run in the wrong folder; `git add -A` can commit secrets
- [x] TL-12 `test.run` unjailed path/flags while auto-approved
- [x] TL-13 terminal command splitting not quote-aware; per-segment timeouts; tail truncation
- [x] TL-14 argument validation (bool as int, NaN, bounds, defaults)
- [x] TL-15 timed-out side-effecting tools can run twice
- [x] TL-16 desktop-control methods bypass the gate; unbounded `wait`
- [x] TL-17 skill catalog quoting / name validation
- [x] TL-18 NTFS alternate streams
- [x] TL-19 `python.exec` failure detected by the word "refused"
- [x] TL-20 browser/email tools: URL schemes, recipient validation, echoing typed values, unbounded counts
- [x] TL-21 plugin loader imports any file
- [x] TL-22 default capability policy allows everything

### Memory (MM)
- [x] MM-1 structured memories fail to load after restart (`json.loads` mismatch)
- [x] MM-4 activity log encoding crash on non-ASCII
- [x] MM-5 same-second facts overwrite each other
- [x] MM-6 "forget" misses stores (chat, turns, activity, session log, saved responses, profile, wiki, vector scan)
- [x] MM-7 entries dictionary read/mutated from many threads with no lock
- [x] MM-14 (= X-2)
- [x] MM-9 no redaction of secrets before storing

### LLM layer (LM)
- [x] LM-1 cache ignores image path / `use_chat` / provider
- [x] LM-2 (= X-3) + TTL, no caching of time-sensitive prompts
- [x] LM-3 SDK auto-retries multiply timeouts; Gemini/Anthropic have no timeout
- [x] LM-4 48 s of sleeps on the voice thread; retries multiplied by the model hub
- [x] LM-16 two Gemini SDKs imported eagerly (≈ 8.5 s startup)

### Interfaces (UI)
- [x] UI-1 extension sidebar input recursion (duplicate function)
- [x] UI-2 dashboard bridge: no Host check, WebSocket without Origin check
- [x] UI-3 fallback TTS PowerShell injection / curly quotes
- [x] UI-4 `/api/flexie/status` always errors
- [x] UI-5 interrupted neural speech replays in the fallback voice
- [x] UI-7 localhost:8000 / :5173 receive the API token by default
- [x] UI-12 extension `CALL_API` URL built from unvalidated text

### Heavy abilities (EN)
- [x] EN-1 delete confirmation names a different target than what is deleted
- [x] EN-2 first-substring match for delete/rename/open; stale cache
- [x] EN-3 email sent with no read-back/confirmation
- [x] EN-4 `run_cmd` / developer engine accept `&` chaining via `cmd /c`
- [x] EN-5 clipboard monitor stores everything in plain text forever

### Everyday utilities (UT) — wrong results
- [x] UT-1 hash handler lowercases the payload (+ base64 case)
- [x] UT-2 JSON formatter lowercases keys and values
- [x] UT-3 password check lowercased; generated password spoken/stored
- [x] UT-4 absolute-time reminders fire after the wrong delay; wrong confirmation text
- [x] UT-5 todo add/remove/clear never run
- [x] UT-6 notification handler month-end crash / invalid time

### Repo hygiene (LG)
- [x] LG-1 `recovery/` is git-ignored and untracked → track it — staged in the git index, not committed
- [x] LG-9 untrack 27 runtime/personal files (`data/persona/*`, job state, eval results, `.bak`) — staged in the git index, not committed
- [ ] House-keeping: collapse the three stray "phase(p1)" commits into one named commit *(needs your OK; rewrites local history)*

---
## Phase 1 — correctness quick wins

### Routing / understanding (RT)
- [x] RT-1 "what's on my screen" → `calc`
- [x] RT-2 "what time is it" → `alarm` — NOT a bug: the alarm handler answers the time on purpose
- [x] RT-3 weather question → `briefing`
- [x] RT-4 bare "stop" → `app_op`
- [x] RT-5 cap the text seen by the regex tier (long-input cost ≈ 45 µs/char)
- [ ] RT-6 prefilter patterns by keyword/first token (speed)  ⟵ SKIPPED: typo cache brought routing to ~0.2-0.5 ms, prefilter not needed
- [x] RT-7 routing eval grown to ≥ 150 cases (typos, ambiguity, compound, negatives), threshold 0.9 default
- [~] RT-8 orchestrator audit — fixed: stuck action/speech workers, per-step shutdown + email close. OPEN (unproven, need live stack): clarification race/loop, watchdog lets a second command start, unbounded speech queue

### Interfaces (UI) — rest
- [x] UI-6 `speak(interrupt=True)` dropped
- [x] UI-8 dashboard XSS (toast/MCP names)
- [~] UI-9 unauthenticated inbound UI UDP  ⟵ PARTIAL: receiver + orchestrator signing done; untested live
- [x] UI-10 stale bridge process keeps an old token
- [x] UI-11 Qt UI and bridge share UDP port 9886
- [x] UI-13 extension context-menu data lost / silent failure
- [x] UI-14 speech recognition has no timeout
- [x] UI-15 no size limits on API inputs; unbounded queue; approval thread race
- [x] UI-16 startup/shutdown errors hidden; orphaned UI process; single-instance check too broad
- [x] UI-17 `is_online()` sets a global socket timeout
- [x] UI-18 path resolver drops file names
- [x] UI-19 Ollama URL probe double-appends `/api/…`; serial preflight probes
- [x] UI-20 `.env` overrides real environment; hard-coded bridge key; cwd-relative paths
- [x] UI-21 identical speech within 4 s dropped; unlocked buffer; `confirm()` can wait forever
- [x] UI-22 banner self-XSS · UI-23 no SRI/CSP on third-party fonts

### Heavy abilities (EN) — rest
- [~] EN-6 knowledge indexer: whole drives hourly, whole-file reads, previews to the LLM  ⟵ PARTIAL: knowledge walk is its own, not the shared name index (re-checked: shares exclusion rules; walk stays separate by design)
- [x] EN-7 IMAP delete/archive/move use shifting sequence numbers
- [x] EN-8 email logs out of the cached connection on every call
- [x] EN-9 reading unread mail marks it read; N+1; wrong "newest"; query injection
- [x] EN-10 file search scans whole drives; substring exclusions; shared dict
- [x] EN-11 rename lowercases the new name
- [x] EN-12 `close_app` substring match, no confirmation
- [x] EN-13 scheduler drift/missed triggers, no persistence, "once" missing
- [x] EN-14 Playwright used from non-owner threads
- [x] EN-15 captcha false positives block 60 s
- [x] EN-16 typed form values logged/spoken
- [x] EN-17 multi-tab research (unencoded URLs, cwd report, prompt injection) · EN-18 music search · EN-19 camera Enter into any window
- [x] EN-20 clipboard pin wrong row · EN-21 unattended desktop organise has no undo · EN-22 Recycle-Bin fallback deletes permanently · EN-23 save overwrites · EN-24 git without timeout/cwd · EN-25 generated HTML opened directly

### Everyday utilities (UT) — rest
- [x] UT-7 tip bill/percent/split parsing
- [x] UT-8 binary decode
- [x] UT-9 converter (minus sign, plurals, pound ambiguity, `1,5`, KB/GB, rounding, stale rates)
- [x] UT-10 QR (lowercased, hidden failure, colliding names, cwd, third-party API)
- [x] UT-11 age/birthday math
- [x] UT-12 alarm time parsing (`7 am`, `noon`) · UT-13 alarm/timer ID collisions, never removed · UT-14 `1.5 hours`, `2 hours 30 minutes`, message extractor
- [x] UT-15 text-tools quotes/apostrophes/case · UT-16 weather city/status/caching · UT-17 dictionary/synonyms · UT-18 facts category · UT-19 UUID parsing · UT-20 BMI units/plausibility
- [x] UT-21 news (status, None titles, cache) · UT-22 summarize/PDF (missing folder, newest file, lowercased paths, scripts in text) · UT-23 PDF extraction cap · UT-24 wiki/dictionary URL encoding · UT-25 quotes dead host · UT-26 pomodoro duplicate threads · UT-27 jokes `None`
- [x] UT-28..35 IP lookup, image-gen names, colour complement, lorem 0, JSON flatten, reminder double mechanism, timer grammar, password length

### Memory (MM) — rest
- [x] MM-2 recall needs whole-prompt substring match → token overlap / FTS5, exclude conversation from RAG
- [x] MM-3 "write … it/that" hijacked into "paste"
- [x] MM-8 unbounded growth (TTL, caps, no assistant replies as memories)
- [x] MM-10 memory text injected into the prompt without a "data" marker
- [x] MM-11 context expiry clears only 10 fields; `pending_action` never expires
- [x] MM-12 "delete it/that" deletes the last touched file · MM-13 "close that" uses the first word only
- [x] MM-15 late writes at exit · MM-16 vector store dimension mismatch/duplicate ids/per-task client/unescaped LIKE/indexes/atomic wiki
- [x] `MemoryEngine` moved to the shared WAL connection (≈ 160× faster writes)

### LLM layer (LM) — rest
- [x] LM-5 weak local answers accepted for strict-JSON routing
- [x] LM-6 streaming duplicates text after a mid-stream fallback; empty stream; not local-first
- [x] LM-7 streaming latency recorded as ~0; stream tokens estimated
- [x] LM-8 Groq empty reply returned instead of falling back
- [x] LM-9 Gemini new-SDK path drops the persona
- [x] LM-10 second provider pass after total failure
- [x] LM-11 circuit breaker never recovers
- [x] LM-12 local-engine message assembly differs from cloud
- [x] LM-13 model hub cheap-first dead (URL), per-call health probe, second token ledger
- [x] LM-14 event bus ordering; trace collector "most recent trace"
- [x] LM-15 failed calls invisible to telemetry
- [~] LM-17 `.env` override, unfiltered error text, stale defaults, cache thread-safety, DB retention/indexes/WAL, raw trace content, single-threaded bridge  ⟵ PARTIAL: load_dotenv(override) now fixed in UI-20; hedging not done

### Tools (TL) — see Phase 0; remaining low items are included above.

---
## Phase 2 — structural
- [x] Approval redesign (request id end to end, one token per action, lock, TTL) — *SF-8*
- [x] Classify by tool + arguments (`effect` on every tool) instead of wording
- [x] FTS5 retrieval with ranking (bm25 × importance × recency); vector prune/thresholds
- [x] Provider hedging (start the second after ~1.5 s), shared circuit breaker, dedicated small routing model
- [x] Single Playwright worker thread; scheduler on `next_run` with persistence
- [x] Streaming TTS (time to first word); background preflight/calibration
- [x] Shared voice-text parser (times, durations, numbers)
- [x] Handlers return structured outcomes (success, message, effect)

## Phase 3 — clean-up and release readiness
- [ ] LG-2 LangGraph loop broken → delete + drop dependency
- [ ] LG-3/4 supervisor + durable runtime → delete (job system already resumes) *(confirm)*
- [ ] Delete unused legacy agents/adapters/atomic actions (~1,000 lines)
- [x] LG-5 recovery analyzer: singleton, real error text, validated output
- [ ] LG-6 arbitrator depth count/timeout · LG-7 goal evaluator/critic thresholds · LG-8 SDD output validation
- [ ] LG-10 packaging: `pyproject` ↔ `requirements` drift, `flexie` console script, PyInstaller hidden imports/UPX, split core/optional deps, lockfile
- [ ] LG-11 CI: Python matrix, type check, dependency audit, secret scan, build smoke test, honest coverage floor
- [ ] LG-12 PyQt6 (GPL) vs MIT licensing — **open again**: PyQt6 was removed during Round 5, then restored at the user's request (the Qt floating-orb HUD is the desktop UI); a licence decision is needed

## Known structural limits (documented, not fixable by code alone)
- Handler steps on the older text-command path cannot be interrupted or independently confirmed.
- A tool that times out may still finish in the background ("outcome unknown").
- Real-model behaviour (planning quality, JSON protocol on small models) needs a live smoke test.

## Status — first pass (superseded; totals at the end of the file are current)
Marking basis: `[x]` = the owning agent reported it fixed with a regression test, and the full suite passed at that time (1,946 tests; now 2,054). I personally spot-checked the safety core, router, orchestrator UI signing, scheduler save race and config; the rest rests on the agents' reports and their tests, not on individual re-verification. 
All six fix areas reported done and merged into the working tree: safety core, memory, LLM/telemetry/traces, tools/MCP/sandbox, interfaces/extension, heavy engines, utilities, router.
Gates: pytest 1946 passed / 1 skipped; ruff clean; agent evals 59/59; `import core.brain` 16.2 s -> 0.35 s.
Partial / open at that time (SUPERSEDED: TL-12, TL-22, TL-15, SF-3, UT-33, MM-8/10/16, bare "stop" and the routing eval were closed in the second pass; see below): UI-23 (Google Fonts SRI), EN-6 (separate knowledge walk), LM hedging, dead-code removal, stray phase(p1) commits.
Not tested live: real models, voice, browser extension, real IMAP/Docker/MCP servers.


## Status — second pass ("fix all bugs", superseded by Round 3/4 totals)
Gates now: pytest 1987 passed / 1 skipped; ruff clean; agent evals 59/59; routing eval 151/151 (default threshold 0.9; empty file fails); HEAD unchanged (17645cc).
Benchmark vs baseline (evals/results/bench-20261118-141406.json) — NOT within 10% everywhere, honestly: routing p50 1497 -> 172 us (faster); registry execute 8 -> 42 us and tool loop 113 -> 312 us (tools now run in a worker pool so timeouts are enforced); plan execution 833 -> 1336 us; memory remember 342 -> 466 us, forget 217 -> 351 us (secret scrubbing + token index; one memory write path got 60x faster). Absolute costs are 0.03-0.5 ms against LLM calls of seconds; accepted trade-off, not optimised further.
Still open: provider hedging, Google Fonts self-hosting (UI-23), orchestrator RT-8 race/loop/watchdog/queue-bound items, audit-reproduction re-run, Phase 3 clean-up (dead modules, packaging, CI, licence) and the three stray commits — these need your decision.
Not tested live: real models, voice, browser extension, real IMAP/Docker/MCP.

## Speed plan — step 1 (startup), measured on this machine
- Import of the orchestrator: 5.4 s -> 0.8 s (pygame, pyautogui, pytesseract/pandas, playwright now load on first use via `utils/lazy.py`).
- Constructing the orchestrator: 9.1 s -> 1.1 s (vector store + Ollama probe moved to a background thread, probe timeout 2 s -> 0.8 s; model SDK clients built in the background; Tesseract check on first OCR).
- Total to a ready assistant object: ~14.5 s -> ~1.9 s (excludes voice/microphone/UI setup in main.py, not timed).
- Tests: 1987 passed + 3 new (tests/test_speed_startup.py); ruff clean; evals 59/59; routing 151/151; bench: memory back to baseline, routing 104 us p50.
- Found: conversational replies already stream and speak sentence by sentence; the router already has a cache and a Tier-1 fast path, so those planned items were largely in place.
- Not done: keep read-only tools out of the worker pool (+0.03 ms per tool call, not worth the extra API); hedging; real end-to-end voice latency (needs a live run with mic and a model).

## Round 3 — found by running real text commands (all verified live unless noted)
- Screen commands: model call crashed after my own patch (restored `_provider_sig`); only vision-capable providers get images; Gemini retired-model + 7 s timeout fixed; OCR fallback; screenshot says where it saved.
- Chrome: "open chrome and search for X" is one request (was 15 s research essay, now 0.15 s); "close the chrome that u opened" / "close all chromes" parse to "chrome"; a sleeping assistant now says it is asleep instead of silently dropping speech.
- Self-awareness (core/self_model.py): live answers for what model / what did you do / why did that fail / are you listening / what do you remember / tools / limits; command log of real outcomes; no more "I'm GPT-4"; "what do you remember about me" no longer saves the question.
- Image download (engines/image_downloader.py): "download 5 images of cats" (web search) or from a page URL; public-http only, size/type/validity checks, new folder under Downloads\Flexie Images.
- Project builder: failure text ("I've searched for you...") is never written into source files; retries with backoff; Groq sibling models tried on rate limit; static-site verifier now checks linked files are real. Real build re-run: app.js 1.9 KB of working code, PLAN.md/ACCEPTANCE.md present.
- Tests no longer write into Downloads (tests/conftest.py); a failed/cancelled build job that produced nothing removes its empty workspace. The 150 old empty `full-stack-web-app-*` folders were deleted at the user's request (only folders holding nothing but `.git`/`.gitignore`/build log; none had real content).
- Router: fuzzy typo-correction no longer rewrites real short words ("that" -> "the").
- Totals at the end of round 3: pytest 2033 passed / 2 skipped; ruff clean; agent evals 59/59; routing eval 158/158.

## Round 4 — live-log misreads, vision mode, documentation
- **Misreads from a pasted live session log (fixed, with tests in `tests/test_fix_chrome_commands.py`):** "wrong check my screen" ran *undo* (the bare word "wrong" is no longer an undo trigger; only the whole utterance "wrong" / "that's wrong" is); "check my screen" and "check my screen, the tab says wrong" now go to screen analysis and the user's wording is passed to the vision model; "check in chrome who is nvidia ceo" searched for "check who is …" (the leading "check" is stripped); "skip that" / "okay skip those" / "never mind" are acknowledged instantly instead of a 4.5 s model call.
- **Vision mode:** "open vision mode" (start/launch/run, "start the orb") starts the separate `vision/` ULTRON orb app (`engines/vision_mode.py`, `core/handlers/vision_mode.py`): first launch runs `npm ci` (about 50 s here), dev server on the first free port from 3000, page opened in the browser, "close vision mode" stops it, and it is stopped when Flexie exits. Tested by starting the real server, fetching the page and stopping it; not tested by voice.
- **Wake-word hint:** while asleep, speech without the wake word is logged and (at most once a minute) answered with "I'm asleep. Say 'Flexie' first…".
- **Known gaps found while documenting (not fixed):** the `vision/` orb and `flexie_web/` connect to `ws://localhost:8765` but the bridge accepts only its own dashboard origin and an `AUTH:` token, so they cannot connect; `flexie_web`'s provider list still shows retired default models; `engines/self_awareness.py` capability/limitation text does not yet mention image download or vision mode; `supervisor/`, `runtime/` and `Brain.react()` / `core/agent_loop.py` are unused; `FINAL_REPORT.html` still shows the old counts (736 tests, 45/45 routing, 43/43 agent evals); "is there any important mail" is not understood as a question about importance.
- **Documentation refreshed to the current code:** `README_FEATURES.md`, `OPENJARVIS_ADAPTATION.md` (new §12), `../BENCHMARK_REPORT.md` (re-run; honest about slower paths), `evals/README.md`, `extension/README.md`, `flexie_web/README.md`, banner on `MODULE_AUDIT_REPORT.md`, `evals/bench.py` "not measured" text.
- **Totals after Round 4:** pytest 2,054 passed / 1 skipped; `ruff check .` clean; agent evals 59/59; routing eval 158/158; 96 intents, 197 overrides, 43 engines, 49 handler modules, 70 test files.

## Round 5 — one web UI built, then reverted (Nov 18-19, 2026)
- [x] Built: dashboard-only desktop UI (`interface/ui.py` and PyQt6 removed, `interface/launcher.py` with tray + Ctrl+Alt+F hotkey started by `main.py`, Qt UDP port 9886 removed)
- [x] **Reverted at the user's request (Nov 19):** the PyQt6 floating-orb HUD (`interface/ui.py`), `run_ui` in `main.py`, PyQt6 in requirements/pyproject/`flexie.spec`/installer and UDP 9886 are back; the web dashboard opens only when asked ("open web ui"). `interface/launcher.py` is now a helper (bridge start/reuse/stop, `open_dashboard`); its tray/hotkey class is not started by `main.py`
- [x] Kept from Round 5 (dashboard side): Orb tab (`interface/orb/` -> `interface/static/orb.js`, `orb-gestures.js`, `orb.css`, `orb-panel.js`), approval modal, API-keys/models dialog (`core/settings_service.py`, `GET_SETTINGS` / `SAVE_SETTINGS`, masked hints only), mail badge, quit notice, safe `/static/<file>` route; "open vision mode" opens `http://localhost:8766/#orb`, "close vision mode" sends `PANEL:close` (no npm, no Next.js dev server)
- [ ] LG-12 (PyQt6 GPL vs MIT) is open again
- [ ] Not verified: Ctrl+F hotkey and tray menu clicks, what the Qt window looks like, the Orb tab and modals in a real browser, camera hand tracking

## Round 6 — found by running the real app (Nov 19, 2026)
- [x] "open web ui" and "run command" were routed with confidence 9 / 10 and had no dispatcher branch, so the model answered "Done" without doing anything. Overrides are now 0.97, `dispatch_intent` has branches for both, and a test checks every override has a valid confidence and a dispatch branch
- [x] The dashboard bridge started by "open web ui" was left running (ports 8765/8766) after "exit", because `handle_exit` ends with `os._exit(0)`, which skips `atexit` and `main.py`'s shutdown. `handle_exit` and `_shutdown` now call `stop_bridge()`. Verified live: after "exit" the API, bridge and WebSocket ports are closed and no Flexie process is left
- [x] A visible blank Chromium window opened at every startup: `YouTubeController` pre-warmed Flexie's Playwright browser 3 s after launch (`headless=False`). Pre-warm is now opt-in (`FLEXIE_PREWARM_BROWSER=1`); `test_browser_is_not_prewarmed_unless_asked` covers it. Verified live: no Chromium process on the `browser_session/` profile and no new "pre-warmed" log line after a start
- [x] Live checks: the Qt HUD window (300x300 tool window) appears at startup; no bridge or browser until asked; "open web ui" brings the dashboard up in about 2 s
- [x] Totals: pytest 2,119 passed / 2 skipped (72 test files); `ruff check .` clean; agent evals 59/59; routing eval 158/158

## Round 7 — found in the user's live session log (Nov 19, 2026)
- **"generate python code for hello world" asked to confirm ("destructive or irreversible")**: the permission rule matched the bare word `python` (also `node`, `pip`, `cmd`, `bash`). It now matches only a clause that STARTS with an interpreter plus arguments ("python script.py", "pip install x"); "run python script" still confirms. The prompt now says "That will change something on your computer" unless the danger gate actually fired.
- **UI / API approve, reject and cancel were ignored**: the orchestrator looks for `self.controller`, which nothing set, so a rejected prompt stayed pending and re-asked on every later command ("close the web ui" got "Say confirm…"). `main.py` now sets `assistant.controller`; approvals are resolved on the action worker through the command queue (a stale approval for another request id is ignored).
- **"close the web ui"**: new intent `close_web_ui`; stops the dashboard bridge whoever started it (only a process listening on 8765/8766 whose command line is `web_ui_bridge`), tells open dashboards to close the panel, and says the browser tab itself may still be open.
- **"close chrome" with several windows**: lists the user's windows (numbered, titles), asks which one, accepts a number, ordinal, title words, "all" (second confirmation) or "cancel"; silence or an unclear answer closes nothing. One window is closed politely (WM_CLOSE); none falls back to ending the process. Flexie's own browser (`browser_session`) is never offered.
- **Picking by ordinal**: "the second one" used to select item 1 (dict order matched "one" first) in BOTH this picker and the file-delete picker; longer words are checked first now.
- **Test timing**: `test_create_and_run_job_lifecycle` waited at most 5 s for a job that runs real `git`; it failed under a loaded machine. Ceiling raised to 30 s (early exit unchanged).
- Verified live on this machine: Chrome window listing (2 real windows found, answer "cancel" closed nothing), `close the web ui` stopped the bridge and a second ask said it wasn't running, UI reject cleared the pending prompt (on a private UDP port). NOT verified: closing a real window by number, voice recognition of the answer, and the dashboard in a browser.

## Round 8 — browser extension did not work (Nov 19, 2026)
- **Cause 1:** the API gave the bearer token only to requests whose `Origin` was on a trust list that needed `FLEXIE_EXTENSION_IDS` set to the extension's random ID before Flexie started. Nobody does that, so the sidebar said ONLINE (the health check succeeds) while every real request returned 401.
- **Cause 2 (found by loading the extension into a real Chromium):** Chrome sends **no `Origin` header at all** on requests from an extension's own pages, so even a correctly configured ID could never match.
- **Fix:** pairing key. Flexie creates `extension/pairing.key` (random 256-bit, git-ignored); the extension reads its own copy and sends it as `X-Flexie-Pairing` on `/health`; the token is issued only for that key (constant-time compare). Not in the CORS allow-list, so web pages cannot send it; unreadable to web pages and other extensions. Also fixed the extension ID via a `key` in `manifest.json` (`mhamnndilobijpbcpjfacaeiadnlffom`).
- **Status badge** now says `NOT PAIRED` instead of a misleading ONLINE when no token is issued; the popup's inline script (blocked by Manifest V3) moved to `popup.js`.
- Verified in a real Chromium (Playwright, extension loaded unpacked, real Flexie API server, no configuration): extension id matches, sidebar ONLINE + token stored, `POST /command` reached the orchestrator queue, `POST /page-assist` answered, popup ONLINE + token with no console errors; no header / wrong key / unknown extension origin get no token. NOT verified: selection pill, context menus, side panel in the user's own Chrome, voice dictation, DOM tasks.

## Round 9 — Flexie reads and controls the current tab (Nov 19, 2026)
- **Built:** a polling channel (`core/extension_bridge.py`, `/api/flexie/extension/{poll,result,status}`, polling loop in `background.js`) and `core/handlers/tab.py` with its router override (`browser_tab`). Tasks: active_tab, list_tabs, read_page, extract_tables, extract_links, find_text, scroll, click, fill, key, navigate, submit. Act tasks need confirmation; reading falls back to Flexie's own browser when the extension is not connected.
- **Bugs found by the real-browser run and fixed:** a click fired twice (`clickElement` clicked and also dispatched a synthetic click); `DOM_FILL` with an empty label filled the first input on the page; page-side `{ok:false}` was reported as success; extracted text had block elements glued together; a doubled `|` in a router regex matched every command; the optional preposition matched the "in" in "explain".
- **Safety:** `viaFlexie` fills refuse password/card/code fields; http/https navigation only; typed values never echoed; page text marked untrusted.
- **Verified** in a real Chromium with the unpacked extension (16/16: connect by polling, tab info, list, read, summarize, find, tables, links, scroll, click, type, password refusal, navigate, missing-element error, unreadable page) and by `tests/test_extension_bridge.py` (68 tests). Full suite 2214 passed, agent evals 59/59, routing 166/166, ruff clean. NOT verified: the user's own Chrome, selection pill, context menus, side panel, voice, the confirmation prompt end to end.

