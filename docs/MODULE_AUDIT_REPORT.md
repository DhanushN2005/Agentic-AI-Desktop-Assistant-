# Flexie — Module-wise Bug Report, Efficiency Review and Improvement Plan

> **Status (updated 2026-11-18, evening): this is a historical audit snapshot.** The findings below describe the code as it was when the audit ran (1,029 tests). Most Phase 0–2 items have since been fixed and are tracked, item by item, in `FIX_CHECKLIST.md`; current measurements are in `../BENCHMARK_REPORT.md` and the current architecture is in `ARCHITECTURE.md`, `../README.md` and `OPENJARVIS_ADAPTATION.md` §12. One correction: "what time is it" routing to the alarm handler is **intended** (that handler answers the time), not a misroute. The body is kept unchanged so findings can still be traced.
> **UI update (2026-11-18, late):** the PyQt6 HUD (`interface/ui.py`) audited here was later replaced by `interface/launcher.py` plus the web dashboard; findings UI-9/UI-11 (the Qt UDP port) and LG-12 (PyQt6 licence) no longer apply to current code.

Date: 2026-11-18 · Repo state: branch `hardening/security-agents-telemetry` · Tests at time of audit: 1,029 passing, ruff clean, 59/59 agent evals.

> **Why this report exists.** The test suite is green, but every test uses fake models and stub tools. This audit looks at what the tests do *not* cover: real-world behaviour, security gaps, speed and accuracy. Passing tests do **not** mean the assistant is bug-free.

---

## 0. How to read this report (trust levels)

Nine read-only audits were run, one per area. Their findings are model output, so each finding carries a trust tag:

| Tag | Meaning |
|---|---|
| **V** | I reproduced it myself by running code in this session |
| **R** | I confirmed it by reading the exact lines myself |
| **A** | The auditor reported it after reading the lines; I did not re-check it |

**Coverage gaps (be aware):**
- The audit of **routing + the orchestrator's internals** did not finish (the auditor stalled and was stopped). For that module I only have my own measurements and a 40-command routing sample. The orchestrator's queues, threads, watchdogs and clarification flow were **not** audited this round.
- Nothing here was run against a live LLM, real voice, the live browser extension, or real email/browser automation.
- Locations (file and line) are in **Appendix B** so the main text stays readable.

---

## 1. Executive summary

**State of the project:** a large, capable prototype whose safety layers, memory and speed have real gaps. The earlier hardening work (permissions, planner, build jobs, telemetry) holds up, but this audit found **three regressions I introduced** and a number of serious older problems.

### 1.1 Regressions introduced this session — fix first

| # | What | Impact | Trust |
|---|---|---|---|
| X-1 | The per-clause danger check does not split on `.` `?` `\n` `&`. "what time is it. delete everything" is judged harmless. | A destructive command after a question sentence runs with **no confirmation** (the old whole-text check caught it). | **V** |
| X-2 | The shared SQLite connection (speed fix) lets one thread's rollback erase another thread's uncommitted write. | Rare silent loss of memory writes under concurrency. | **V** |
| X-3 | The "don't cache failures" fix only covers empty replies. A non-empty failure message ("All AI providers are unavailable…") is still cached and keeps being served after you reconnect. | Assistant keeps saying the failure text for a repeated question. | **V** |

### 1.2 Top risks found (older problems)

1. **Structured memory vanishes on every restart** — facts/preferences you tell it to remember are not loaded back (pre-existing). **V**
2. **The file tools can read and write `.env`, `.git/hooks`, `core/safety.py`, the MCP config and skills** — the "jail" is the whole project folder. **V**
3. **The terminal allowlist is effectively "run anything"** (`python -c`, `npx`, `pip install <url>`, `git -c …`), gated only by one confirmation. **R**
4. **Permission classification fails open**: anything not matched by wording rules (e.g. "email boss that I quit", "wire 500 dollars to john", "get rid of my old files") needs no confirmation. **V**
5. **The browser extension's typed/voice input is broken** (a function is declared twice, causing infinite recursion). **R**
6. **The dashboard web bridge can be taken over by DNS rebinding** (it never checks the Host header, and the WebSocket has no Origin check). **R**
7. **Startup takes ~17 s**; ~8.5 s of it is two Google Gemini SDKs loaded eagerly even when Gemini is never used. **V**
8. **Wrong answers from small handlers**: reminders at "5 pm" fire in 5 minutes, `sha256 "Hello"` hashes `hello`, `convert -40 c to f` fails, todo add/remove/clear never works as advertised. **V**
9. **Personal and runtime files are tracked in git**, while a real source folder (`recovery/`) is accidentally git-ignored. **V**

### 1.3 Baseline measurements (this machine, one run)

| Measure | Result |
|---|---|
| Cold import of the orchestrator | **16.8 s** (the LLM layer alone: 13.9 s; two Gemini SDKs ≈ 8.5 s of that) |
| Router speed, normal commands | p50 1.8 ms; the first call can take ~79 ms |
| Router speed, long input | **~45 µs per character** → 5,000 chars ≈ 0.22 s, 20,000 chars ≈ 0.9 s (no hang, no catastrophic backtracking) |
| Router patterns | 96 intent patterns + 178 natural-language overrides, tried in sequence |
| Slowest tests | job smoke tests (~5–10 s), preflight tests (~5 s each) |
| Memory write | 0.1–0.5 ms (after the earlier fix); `MemoryEngine` is still on the slow path (~13 ms/write) |
| Routing accuracy on my 40-command sample | 4 confident misroutes (see §3.2) while the 45-task eval scores 100% |

---

## 2. Module map and status

| # | Module | Open bugs (reported / reproduced by me) | Biggest issue | Section |
|---|---|---|---|---|
| 1 | Ways to talk to it (voice, UI, dashboard, extension, API, startup) | 23 / 4 | Extension input broken; dashboard takeover; TTS injection | §3.1 |
| 2 | Understanding requests (router, orchestrator) | partial | Confident misroutes; long-input cost; internals unaudited | §3.2 |
| 3 | Planning and doing multi-step tasks | 67 fixed earlier | Structural limits only | §3.3 |
| 4 | Tools (registry, coding tools, MCP, skills, sandbox, desktop) | 22 / 2 | Jail covers secrets; allowlist too broad; MCP trust | §3.4 |
| 5a | Heavy abilities (files, email, browser, system, automation) | 25 / 3 | Delete targets wrong file; email unconfirmed; `&` chaining | §3.5 |
| 5b | Everyday utilities (reminders, converters, hash, todo…) | 35 / 3 | Payloads lowercased; wrong results | §3.6 |
| 6 | Safety and control | 15 / 5 | Fails open; clause-split regression; approval design | §3.7 |
| 7 | Memory | 15 / 2 | Memory lost on restart; weak recall; no retention | §3.8 |
| 8 | AI models, telemetry, traces, evals | 19 / 2 | Stale cache; 48 s freezes; retry multiplication | §3.9 |
| 9 | Legacy / unconnected code, packaging, CI | 14 / 3 | Dead modules; broken packaging; tracked personal files | §3.10 |

---

## 3. Module-by-module

### 3.1 Module 1 — Ways to talk to it (voice, desktop window, dashboard, extension, API, startup)

**What it does:** takes your voice, typing, browser extension and REST/SSE API requests and delivers them to the assistant.

**Open bugs**

| ID | Sev | Problem (plain language) | Trust |
|---|---|---|---|
| UI-1 | High | Extension sidebar: typed and voice input crash with infinite recursion (a handler function is declared twice). Only the chip buttons work. | R |
| UI-2 | High | Dashboard web bridge never checks the Host header; a malicious website can rebind to localhost, read the embedded token, then drive the assistant over the WebSocket (which also has no Origin check). | R |
| UI-3 | High | Fallback voice (Windows speech) builds a PowerShell command from the spoken text, breaking on curly quotes (`’`) and allowing command injection from web/email text. | A |
| UI-4 | High | `GET /api/flexie/status` always returns an error (calls a function without its required argument). | R |
| UI-5 | High | Interrupting spoken neural speech makes the same sentence play again in the fallback voice; after 3 stops the neural voice is disabled for the session. | A |
| UI-6 | Med | `speak(..., interrupt=True)` is often dropped (the new reply is discarded). | A |
| UI-7 | Med | Any app on localhost ports 8000 or 5173 can get the API token (those origins are allowed by default). | R |
| UI-8 | Med | Dashboard XSS: toast and MCP names are inserted as unescaped HTML. | A |
| UI-9 | Med | The UI's inbound UDP port (9886) accepts unauthenticated messages (fake approval popups, QUIT). | A |
| UI-10 | Med | A stale bridge process survives restarts and keeps an old token, so every dashboard command is rejected. | A |
| UI-11 | Med | The Qt UI and the web bridge bind the same UDP port, so state updates reach only one of them. | A |
| UI-12 | Med | Extension `CALL_API` builds the URL from unvalidated text (`@evil.com/x` would send the token elsewhere) with no sender check. | R |
| UI-13 | Med | Extension context-menu actions lose their extracted data and can silently fail on restricted pages. | A |
| UI-14 | Med | Google speech recognition has no timeout; a hung request freezes the voice thread. | A |
| UI-15 | Med | No size limits on API inputs; unbounded command queue; approvals run on a random thread and `request_id=None` approves whatever is pending. | A |
| UI-16 | Med | Startup/shutdown errors are hidden (API port already in use is logged at debug level); the UI process can be orphaned; the single-instance check can refuse to start because of an unrelated Python process. | A |
| UI-17 | Med | `is_online()` sets a process-wide 2-second socket timeout, affecting later network calls. | A |
| UI-18..23 | Low | Path resolver drops file names; Ollama URL probe double-appends `/api/…`; `.env` overrides real environment variables; identical speech within 4 s is dropped; banner self-XSS; no SRI on third-party fonts. | A |

**Efficiency / speed / accuracy improvements**

| Change | Benefit | Effort |
|---|---|---|
| Start neural TTS playback after the first chunk instead of synthesising the whole reply | Big drop in time-to-first-word (the main felt latency) | M |
| Run mic calibration and preflight probes in the background; drop the voice enumeration at startup | Several seconds off launch | S–M |
| Partial speech recognition: send only the last few seconds, skip when a request is in flight | Faster final transcript, less traffic | S |
| Reuse one UDP socket for UI updates; use a fast RMS | Less CPU in the audio loop | S |
| Extension: stop polling every 4–5 s when the panel is hidden; poll on tab activation | No constant wakeups | S |
| Cache the `Brain` used by page assist; truncate page text on the client | Lower latency/bandwidth | S |

**Plan**
1. *Now (S):* rename the duplicate extension function; validate `CALL_API` endpoints; add Host and Origin checks to the bridge; default allowed origins to the dashboard only; pass TTS text via stdin; fix the status endpoint.
2. *Next (S–M):* HMAC-sign UI-bound UDP messages; escape dashboard HTML; kill the bridge on exit; size limits on every endpoint.
3. *Later (M):* streaming TTS; background preflight; one UI subscriber list instead of shared ports.

---

### 3.2 Module 2 — Understanding requests (router, orchestrator)

**What it does:** turns a sentence into an action, decides simple vs multi-step, and coordinates everything.

> **Coverage gap:** the dedicated audit did not finish. What follows is my own sampling and the earlier fixes.

**Confirmed by me (V)** — routing a realistic 40-command sample:

| Command | Routed to | Problem |
|---|---|---|
| "what's on my screen" | `calc` (0.95) | Should be a screen-analysis intent |
| "what time is it" | `alarm` (0.95) | NOT a bug: the alarm handler intentionally answers the current time |
| "what's the weather in delhi" | `briefing` (0.95) | Probably should go to weather (judgement call) |
| "stop" | `app_op` (1.00) | Bare "stop" is treated as an app operation |
| "delete the old report", "find my resume", "call mom" | `conversational` (0.0) | Fall to the LLM instead of the file/contact handlers |

5 of 40 commands were routed below 0.75 confidence — each of these triggers an extra LLM call and may trigger a spoken clarification question.

**Other findings**
- Router cost grows linearly with input length (~45 µs/char): a dictated paragraph stalls it for a second or more (V).
- The 45-task routing eval is too easy (short canonical phrases, no typos/ambiguity/negatives) so 100% accuracy is misleading (V, plus the LLM-layer audit).

**Already fixed earlier this session:** one route-resolution order (deterministic beats learned), router runs once per command, authoritative overrides skip the planner, plans return a real success/failure.

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| Cap the text the regex tier sees (e.g. 300 chars); long text goes straight to the LLM tier | Removes the long-input stall | S |
| Prefilter patterns by first token / keyword bucket, or one compiled alternation per bucket | Several-fold speed-up of the 1.8 ms hot path | M |
| Grow the routing eval to 150+ cases with typos, ambiguity, compound and negative commands; make `--min-accuracy 0.9` the default gate | Catches the misroutes above | M |
| Fix the four misroutes (screen/calc, time/alarm, weather/briefing, bare "stop") and add them as eval tasks | Direct accuracy gain | S |

**Plan**
1. Add the misroute cases to the eval first (they must fail), then fix the patterns.
2. Re-run the orchestrator audit (queues, threads, watchdog loops, clarification flow, controller confirmation) — this is the largest unaudited area.

---

### 3.3 Module 3 — Planning and doing multi-step tasks

**Status:** all 67 reported bugs (planner, runner, run limits, specialists, older workflow runner, build jobs) were fixed earlier and verified; 123 regression tests plus job tests cover them.

**Remaining structural limits (not bugs, but real):**
- A step that goes through the older text-command path cannot be interrupted or independently confirmed; it is reported as "ran, couldn't confirm".
- A tool that times out may still finish in the background (a timeout means "outcome unknown").
- The simple planner cannot fill in a tool's arguments, so those steps use the handler path.
- When a traceback has no workspace frame, the build healer guesses a source file.

**Improvement ideas**

| Change | Benefit | Effort |
|---|---|---|
| Give handlers a structured return (success, message, effect) | Real outcome checks instead of "ran" | L |
| Per-call approval tokens instead of a global permission level (see §3.7) | Safer concurrent approvals | M |
| Test the planner and specialists with a real local model; record plan quality | The biggest unverified area | M |

---

### 3.4 Module 4 — Tools (registry, coding tools, MCP, skills, sandbox, desktop control)

**What it does:** the typed list of things the assistant may do, with permissions, timeouts and external tool servers.

| ID | Sev | Problem | Trust |
|---|---|---|---|
| TL-1 | High | The file jail is the whole project folder. `file.write` can write `.git/hooks/pre-commit` (runs on the next commit), `data/mcp_servers.json` (a command that runs at next start), `core/safety.py`, or add a skill; `file.read` can return `.env` (API keys) and the token file. | **V** |
| TL-2 | High | The terminal allowlist checks only the first word. `python -c`, `node -e`, `npx <pkg>`, `pip install <url>`, `git -c core.sshCommand=…`, `rg --pre`, `robocopy`/`xcopy` into the Startup folder are all allowed. | R |
| TL-3 | High | `python.exec`: no process/CPU/privilege limits on the container, the container is never removed if an error occurs, and `timeout` is unbounded. | A |
| TL-4 | Med | MCP server error output is never read; a chatty server fills the pipe and hangs every call. | A |
| TL-5 | Med | MCP tool permission is guessed from the name; `run_command`, `exec`, `upload`, `install`, `kill` become "read-only" (no confirmation). | A |
| TL-6 | Med | Untrusted-content marking is applied only on success, so injected text in an *error* reply is not marked. | A |
| TL-7 | Med | Tool output (MCP, full `git diff`) is unbounded and unlabelled — cost, speed and injection volume. | A |
| TL-8 | Med | MCP: a server message with an `id` can complete someone else's request; empty `{}` results count as failure; JSON-RPC errors are lost; stdin writes have no lock/timeout. | A |
| TL-9 | Med | MCP lifecycle: replacing a server leaks the old process; Windows `terminate()` leaves grandchildren; tool names `mcp_{server}_{tool}` can collide and overwrite built-ins; one bad tool list aborts the whole server. | A |
| TL-10 | Med | `file.patch` rewrites every line ending on Windows and fails on non-UTF-8 files. | A |
| TL-11 | Med | `git.*` and `code.search` run in the process folder, not the project; `git add -A` can commit another repo, including untracked secrets. | A |
| TL-12 | Med | `test.run` accepts any path/flags (`-p evil_mod`) and is auto-approved as read-only while running repository code. | A |
| TL-13 | Med | Terminal command splitting is not quote-aware (`git commit -m "fix; thing"` breaks); Windows quote handling leaves literal quotes; each segment gets the full timeout. | A |
| TL-14 | Med | Argument validation: `True` passes as a number, NaN passes, no bounds, defaults are never applied. | A |
| TL-15 | Med | Timed-out side-effecting tools can run twice if retried. | A |
| TL-16..22 | Low | Desktop-control methods bypass the gate; skill catalog quoting; NTFS alternate streams; failure detected by the word "refused"; browser tools accept `file:`/`javascript:` URLs and echo typed values; plugin loader runs any file; the default capability policy allows everything. | A |

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| Write deny-list (`.git/`, `.env*`, tokens, `data/mcp_servers.json`, `core/`, `skills/`, `sandbox/`) and block reads of secrets; longer term a separate `workspace/` write root | Closes TL-1 | S → M |
| Per-binary subcommand allowlist (e.g. `git status|diff|log|add|commit`, `npm test`); reject `-c`, `-e`, `--exec`, `--pre`, `-p`; jail path arguments | Closes TL-2/TL-12 | M |
| MCP tools default to *confirm*; explicit per-server read-only list; drain stderr; ignore server-initiated messages; cap and label output | Closes TL-4..9 | S–M |
| Cache one Docker client; pre-pull the image; clamp `timeout`; kill/remove containers in `finally` | Faster and safer `python.exec` | S |
| Stream `file.read` ranges; cache skill discovery by modified time | Less I/O | S |

**Plan:** Week 1 — TL-1, TL-2, TL-5, TL-3. Week 2 — the rest of MCP, git/test.run, validation.

---

### 3.5 Module 5a — Heavy abilities (files, email, browser, system, automation, music, vision)

| ID | Sev | Problem | Trust |
|---|---|---|---|
| EN-1 | High | Delete confirmation names a different target than what is deleted (words stripped anywhere: "theme.txt" → "me.txt"; the delete then re-resolves the raw command). | R |
| EN-2 | High | Delete/rename/open pick the **first substring match** in directory order; "delete report" removes whichever of `report_final.docx`/`report_2019.xlsx` is listed first; cached matches are never re-validated. | A |
| EN-3 | High | Email is sent immediately with no read-back or confirmation; the recipient/topic come straight from speech recognition. | A |
| EN-4 | High | `run_cmd` allows only prefixes like `echo `/`dir ` and then runs the whole string through `cmd /c`; `echo hi & del /q C:\…\*` passes. Same gap in the developer engine (single `&` not blocked). | R |
| EN-5 | High | The clipboard monitor stores every clipboard change in plain text every 2 s (passwords, OTPs), with no cap, expiry or opt-in. | A |
| EN-6 | High | The knowledge indexer walks the whole home folder and `D:\` hourly (includes AppData, browser profiles), reads whole files, sends previews to the LLM, never prunes deleted files, and rebuilds from scratch every restart. | A |
| EN-7 | Med | IMAP delete/archive/move use sequence numbers that shift after a delete (wrong message hit); folder names unquoted. | A |
| EN-8 | Med | Every email call logs out of the cached connection, so the 60 s reuse never works (full login each call; 12 `logout()` calls). | R |
| EN-9 | Med | Reading unread mail marks it read; search is N+1; "newest" uses arbitrary set order; the search query can break the IMAP command. | A |
| EN-10 | Med | File search scans whole drives with substring exclusions (skips any path containing "Windows"/"$"), no depth limit, shared dict across threads. | A |
| EN-11 | Med | Rename lowercases the new name ("Q3 Report" → "q3 report"). | A |
| EN-12 | Med | `close_app` matches by substring and can terminate unrelated processes (and Flexie's own Chrome) without confirmation. | A |
| EN-13 | Med | Scheduler: daily jobs fire only if a check lands exactly in that minute (drift loses it), missed triggers are never caught up, jobs are not persisted, the documented "once" trigger is not implemented. | A |
| EN-14 | Med | Browser engine "adopts" a Playwright session from another thread (breaks with a swallowed greenlet error); only the YouTube controller uses a worker thread. | A |
| EN-15 | Med | Captcha detection triggers on any page that mentions "Cloudflare"/"Verify you are human", blocking up to 60 s repeatedly. | A |
| EN-16 | Med | Typed form values (including passwords) are logged and spoken on mismatch. | A |
| EN-17..19 | Med | Multi-tab research builds URLs unencoded, writes a report to the working folder and feeds page text into the prompt; music search is unescaped and case-sensitive and walks the home folder; the camera launcher presses Enter into whatever window has focus. | A |
| EN-20..25 | Low | Pin picks the wrong clipboard row; the unattended desktop-organise job (daily 18:00) has no undo; failed Recycle-Bin falls back to permanent delete while saying "deleted"; save overwrites existing documents; git calls without timeout/cwd; generated HTML opened directly. | A |

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| One resolver used for confirm and delete: show the full path, require an exact match, list candidates when several match | Closes EN-1/2/11 | S |
| Read-back plus `voice.confirm` before every send/forward/reply | Closes EN-3 | S |
| Drop `cmd /c`; run argv with `shell=False`; reject `& < > ^ %` and newlines | Closes EN-4 | S |
| Index only Documents/Desktop/Downloads, skip hidden/AppData, cap at ~1 MB, persist mtimes, prune missing files, use sets; share one name index between files, music and knowledge | Privacy and large speed gains | M |
| Email: one locked connection, UIDs, `BODY.PEEK[]`, no logout per call | Biggest email speed/correctness win | M |
| Scheduler on a stored `next_run`; one dedicated Playwright worker thread | Reliability | M |

---

### 3.6 Module 5b — Everyday utilities (reminders, alarms, converters, hash, todo, weather, news…)

**Root cause for many bugs:** handlers lowercase the whole command and extract the payload from the lowercase copy, corrupting hashes, base64, JSON, URLs, QR data, passwords and file paths.

| ID | Sev | Problem | Trust |
|---|---|---|---|
| UT-1 | High | `sha256 "Hello"` hashes `hello`; base64 decode fails (case-sensitive); filler words end up in the payload. | **V** |
| UT-2 | High | JSON formatter lowercases keys and values. | A |
| UT-3 | High | Password check reads the lowercased password ("Add uppercase" when it has one); generated passwords are spoken and stored in context. | A |
| UT-4 | High | "remind me at 5 pm" says 5:00 PM but fires in 5 minutes; "in a minute" is announced as 5 minutes; "in 30 seconds" as 0 minutes. | **V** |
| UT-5 | High | Todo: the generic "list" check runs first, so add/remove/clear with "list"/"todo" in the phrase only read the list back (the handler's own examples fail). | A |
| UT-6 | High | Notification handler crashes on the 30th/31st (`day+1`) and on "at 25:00". | A |
| UT-7 | High | Tip: the first number is taken as the bill ("tip 20% on $50" → bill $20); splitting ignores `$`. | A |
| UT-8 | High | Binary decode treats a spaced string as one chunk (wrong character). | A |
| UT-9 | High | Converter: `-40 c to f` fails (no minus sign); "pounds" unknown; pound is ambiguous (weight vs currency); `1,5 km` read as 15; KB=1000 but GB=1024; fixed 2-decimal rounding; stale hard-coded currency rates. | **V** (minus sign, pounds) |
| UT-10 | High | QR: content lowercased; failure hidden behind "generated"; 16-bit non-deterministic file names collide; written to the working folder; data sent to a third-party API. | A |
| UT-11 | High | Age/birthday: fixed 30-day month borrow, "tomorrow" says 0 days, Feb-29 rejected, future dates give negative ages. | A |
| UT-12..14 | Med | Alarm accepts only `H:MM` ("7 am" fails); alarm/timer IDs collide after cancel; "1.5 hours" → 5 hours; "2 hours 30 minutes" → 2 hours; notification message extractor strips every "to"/"about". | A |
| UT-15 | Med | Text tools: apostrophes treated as quotes (`uppercase "don't stop"` → "DON"), title-case, wrap and sentence-count defects. | A |
| UT-16..27 | Med | Weather city regex captures filler words and reports "Clear sky" on API errors; dictionary/synonym lookups use the whole sentence; facts ignore the category; UUID batch/version parsing; BMI units (metres treated as cm); news/summarize/PDF/wiki/quotes (dead API host)/pomodoro edge cases; jokes can speak "None". | A |
| UT-28..35 | Low | IP lookup over HTTP; image-gen file names; colour complement is the RGB inverse; lorem 0 words crashes; JSON flatten drops empty containers; reminder double mechanism can speak twice; timer grammar ("1 minutes"); password length not validated. | A |

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| Stop lowercasing payloads (use the original text for the payload, the lowercase copy only for keyword matching) | Fixes UT-1/2/3/10/15 and the summariser at once | S |
| One shared parser for times, durations and numbers ("5pm", "7 am", "noon", "in 1.5 hours") | Fixes UT-4/12/14 and removes four duplicate regexes | M |
| TTL cache (~10 min) for weather/news, indefinite for geocoding; shared HTTP session; check status codes and report "service unavailable" | Speed and honest errors | S |
| Local QR library (`qrcode`/`segno`); stdlib `calendar`/`dateutil` for ages | Offline, correct | S |
| Persist alarms/timers; use a counter or UUID for IDs; pomodoro on `Event.wait` | Correctness and reliability | S–M |
| Cap inputs (lorem, UUID count, password length, summary text, PDF pages) | Prevents runaway work | S |

---

### 3.7 Module 6 — Safety and control

**What it does:** blocks dangerous commands, asks for confirmation, rates actions, and isolates code.

| ID | Sev | Problem | Trust |
|---|---|---|---|
| SF-1 | High | **Fails open:** `classify_action` returns read-only when nothing matches. Ungated examples: "email boss that I quit", "wire 500 dollars to john", "get rid of my old files", "nuke the downloads folder", "reply all", "send it", "deploy", "publish the site", "factory reset", "zzzz qwerty". | **V** |
| SF-2 | High | **Regression (X-1):** actions after `.`/`?`/newline/`&`/` - ` are judged harmless when a question comes first; "wipe", "nuke", "uninstall" are not recognised as new commands. | **V** |
| SF-3 | High | Mail send/reply API endpoints call the engine directly, skipping every gate and confirmation (a leaked token can send mail). | A |
| SF-4 | High | MCP tool permission guessed from names (see TL-5). | A |
| SF-5 | High | Desktop-control calls are classified by a single word and the untrusted-content rule never applies to them; an injected "click"/"type"/"hotkey" is allowed. | A |
| SF-6 | Med | Blacklist bypasses (all PASS): `Remove-Item -Recurse C:\x` (flags first), `rm --recursive --force /`, zero-width/fullwidth characters, `shutdown /s /t 0`, `iex(irm …)`, `Stop-Computer`, `Format-Volume`, `diskpart`, `DELETE FROM users`. | **V** |
| SF-7 | Med | Restricted words use substring matching: "Essex", "Middlesex", "Sussex", "unisex", "adult ticket", "casino royale" are blocked with a security alert. | **V** |
| SF-8 | Med | Approval design: one global pending slot (a later request overwrites it); "confirm" with no id approves whatever is pending; an approval for action B auto-approves action A; the escalation is process-wide for 60 s (other threads ride along); no request expiry; no locking. | A |
| SF-9 | Med | Level inversions and false alarms: "pay attention" and "checkout the new branch" are DANGEROUS; "play sleep sounds" is SENSITIVE; "turn off the firewall" is read-only. | A |
| SF-10 | Med | Any depth-0 command (scheduler, API, automation) clears the untrusted-content marker set by the user's turn. | A |
| SF-11 | Med | Confirmation matcher: "do it", "sure thing", "haan" are not confirmations; a stale "ok" later can run a pending delete (no timeout when inactive). | A |

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| Deny by default: unknown wording, tools and MCP tools default to *confirm* | Closes SF-1/4/5 as a class | S–M |
| Split on `. ? ! \n & –` and add wipe/nuke/uninstall/shred/trash/overwrite as danger verbs; benign only if the question is the *first token of the sentence* and no danger verb follows | Closes the regression | S |
| Add the missing intent patterns (send/reply-all/wire/venmo/publish/deploy/format the drive …) | Immediate coverage | S |
| Normalise (NFKC, strip zero-width), tokenise flags; word-boundary restricted words | Closes SF-6/7 | S |
| Redesign approvals: request id end-to-end, one token per action, a lock, a TTL | Safe concurrent approvals | M |
| Longer term: classify by *tool + arguments* (read/write/delete/send/spend `effect` on every tool) instead of wording | Accurate and stops "pay attention" false alarms | L |

---

### 3.8 Module 7 — Memory

| ID | Sev | Problem | Trust |
|---|---|---|---|
| MM-1 | High | Plain-string memories are saved raw but loaded with `json.loads`; after any restart **all structured memories fail to load** (rows stay in the DB, but the next wiki export can overwrite the readable wiki with an empty one). | **V** |
| MM-2 | High | Recall is nearly useless: search needs the *whole prompt* to be a substring of a key/value/tag; the only thing that matches is the user's own just-saved utterance, which is echoed back into the prompt. | A |
| MM-3 | High | "write a function that sorts a list" is rewritten to "paste the last response" by a greedy follow-up rule. | A |
| MM-4 | High | The activity log opens with the default Windows code page; any non-ASCII utterance (e.g. Hindi, emoji) raises an error. | A |
| MM-5 | Med | Two facts in the same second overwrite each other (timestamp key). | A |
| MM-6 | Med | "Forget" misses: conversation and topic tables, chat history, turns, activity log, session log, saved last-response rows, profile, both wiki copies (stale for 5 s), and a Chroma search that scans everything and truncates at 20. | A |
| MM-7 | Med | The memory dictionary is read and mutated from several threads with no lock ("dictionary changed size" errors swallowed; the wiki silently stays stale). | A |
| MM-8 | Med | Unbounded growth: every utterance and reply is stored forever, loaded into RAM at startup and rewritten into the wiki every 5 s; reply keys share prefixes and overwrite each other. | A |
| MM-9 | Med | No redaction: passwords, API keys and OTPs spoken to the assistant are stored in several databases, plain-text wikis, the log and the vector store. | A |
| MM-10 | Med | Stored memory text is placed in the system prompt without a "this is data" marker (a spoken web summary becomes a standing instruction). | A |
| MM-11 | Med | Context expiry clears only 10 fields; stale `last_query`/`last_url`/`last_selector` make "click it" click an old element; `pending_action` never expires. | A |
| MM-12/13 | Med | "delete it/that" deletes whichever file was last touched; "close that" uses only the first word of the app name ("Visual Studio Code" → "close Visual"). | A |
| MM-14 | Med | **Regression (X-2):** shared SQLite connection interleaves transactions between threads/proxies (lost writes). | **V** |
| MM-15 | Low | Late writes at exit open an unclosed connection; last writes can be lost. | A |
| MM-16.. | Low | Vector store dimension mismatch between embedding models; duplicate ids; a new vector client per agent task; unescaped LIKE in `search_memory`; missing indexes; wiki written non-atomically. | A |

**Measured:** `MemoryEngine` writes still cost ~12.9 ms (rollback journal + fsync) vs 0.08 ms on the shared WAL connection; `MemoryManager.search` over 20,000 entries takes ~22 ms (linear scan).

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| Fix the load/save mismatch (always `json.dumps`, with a migration that falls back to the raw string; per-row try/except) | Restores memory across restarts | S |
| Token-overlap or SQLite FTS5/BM25 retrieval × importance × recency; exclude conversation entries from RAG; distance threshold on vector hits | Recall that actually works; fewer wasted tokens | S–M |
| Retention: TTL for conversation entries (7–30 days), caps on chat tables, periodic vector prune; do not store assistant replies as memories | Bounded size and RAM | S |
| One redaction function applied before every store path (and skip the vector store for flagged text) | Privacy | M |
| Move `MemoryEngine` to the shared WAL connection | ~160× faster writes | S |
| RLock around the entries dictionary; atomic wiki writes; commit-on-write in the connection proxy | Closes MM-7/14 | S |
| Wrap memory/RAG text in a marked "untrusted notes" block | Prompt-injection hardening | S |

---

### 3.9 Module 8 — AI models, telemetry, traces, evals

| ID | Sev | Problem | Trust |
|---|---|---|---|
| LM-1 | High | Response cache ignores the image path: asking "what's on my screen" with two different screenshots returns the first answer. | **V** |
| LM-2 | High | **Incomplete fix (X-3):** non-empty failure text is cached; time-sensitive prompts ("time", "weather", "news") are cached with no expiry. | **V** |
| LM-3 | High | The per-request timeout is not the real timeout: SDK clients retry 2× on top, so a failing provider costs ~22 s; Gemini and Anthropic have no timeout (Anthropic's default is 600 s). All providers failing can take 80 s or more. | A |
| LM-4 | High | For a fixed provider, a rate-limit error makes `ask()` sleep 8 + 16 + 24 s on the voice thread (48 s of silence), and the model hub wraps it in another 3 attempts. | A |
| LM-5 | High | Local-first accepts a weak/empty local answer (default tiny model, 30 s timeout); the router's strict-JSON request often fails on it and silently falls back. | A |
| LM-6 | Med | Streaming: if a provider fails mid-stream the fallback repeats the whole answer (user hears partial + full); a missing local model gives an empty stream with no fallback; streaming is not local-first. | A |
| LM-7 | Med | Streaming latency is recorded as ~0 s (timer starts after the stream ends); stream token counts are always estimates. | A |
| LM-8 | Med | A Groq empty reply (reasoning tokens used up the budget) is returned instead of trying the next provider; callers can receive `None`. | A |
| LM-9 | Med | The Gemini new-SDK path drops the persona/system prompt when the default prompt is in use. | A |
| LM-10 | Med | After every provider fails, a second manager pass retries all of them again (Mistral up to 20 s), building a new client each time. | A |
| LM-11 | Med | The provider circuit-breaker never recovers (the reset branch is unreachable) — three transient failures disable a provider until restart. | A |
| LM-12 | Med | Local-engine message assembly differs from the cloud path (no turn limit, no de-duplication). | A |
| LM-13 | Med | The model hub's "cheap-first" path probably never works (double-appended `/api/…` URL), probes health on every call, and keeps a second, disagreeing token ledger. | A |
| LM-14 | Med | Event bus does not preserve order for equal priorities (events arrive shuffled, corrupting trace step timing); the trace collector attaches events to "the most recent trace". | A |
| LM-15 | Med | Failed LLM calls are invisible to telemetry (only successes recorded), so latency/cost reports look better than reality. | A |
| LM-16 | Med | Importing the module loads **two** Google SDKs (≈ 8.5 s) even when Gemini is unused. | **V** |
| LM-17.. | Low | `.env` overrides real environment variables; provider errors printed unfiltered; retired Anthropic model default; installed `anthropic` package fails to construct (silently disabled); cache not thread-safe; no retention or index on the telemetry/traces databases; traces store raw queries; the OpenAI-compatible bridge is single-threaded and compares tokens with `==`. | A |

**Latency budget of one LLM-routed command** (from the code): best case ≈ 0.5–1.5 s per LLM call × 2 (router + answer); with Groq flaky ≈ 25 s per call; with all providers down 60–100 s or more.

**Improvements**

| Change | Benefit | Effort |
|---|---|---|
| `max_retries=0/1` on every SDK client; explicit timeouts for Gemini/Anthropic | Bounds each provider to ~7 s | S |
| Replace the 8/16/24 s sleeps with immediate fallback to the next provider | Removes the 48 s freeze | S |
| Cache key: include image path+mtime, `use_chat`, provider, a TTL (30–60 s; 0 for time-sensitive); never cache failure text; add a lock | Fixes LM-1/2 | S |
| **Lazy-import the Gemini SDKs** (and drop the deprecated one) | **≈ −8.5 s startup** | S |
| A small fast dedicated model for routing (temperature 0, ~150 tokens, validated intent) instead of local-first tiny model | Faster, more reliable routing | M |
| Hedge providers (start the second after ~1.5 s) | Worst case ≈ 8 s instead of ≈ 21 s | M |
| Record failed attempts and fix the streaming timer; add retention and an index on `trace_steps.trace_id`; WAL for the trace store | Honest numbers, bounded DB | S |
| Event bus `(priority, sequence)` tie-break | Correct trace timing | S |
| Eval: 150+ varied cases, test `route_dynamic` with a fake LLM, default threshold 0.9, fail on empty task files | Real regression gate | M |

---

### 3.10 Module 9 — Legacy / unconnected code, packaging, CI

**Dead (no non-test importer):** supervisor, durable runtime, atomic actions, three legacy agents, five adapters, the LangGraph agent loop (reachable only through a method nobody calls), the gesture web app. About 1,000 lines of Python plus a large lockfile.

| ID | Sev | Problem | Trust |
|---|---|---|---|
| LG-1 | High | `.gitignore` contains `recovery/`, so the failure-analyzer module **is not in the repository**; a clean clone or CI checkout lacks it and the workflow runner silently skips recovery. | **V** |
| LG-2 | High | The LangGraph agent loop is broken end to end (state key missing, tool calls never read, final result lost) and its errors are swallowed. | A |
| LG-3 | Med | Supervisor never restarts a crashed worker (the `finally` clears the flag the monitor checks); a stale-heartbeat restart starts a duplicate thread. | R/A |
| LG-4 | Med | Durable tasks: one corrupt entry aborts the load and the next save overwrites the file (data loss); non-atomic writes; no lock; checkpoint after the side effect (resume re-runs it). | A |
| LG-5 | Med | The recovery analyzer is rebuilt per low-quality step (duplicate event subscribers pile up), is fed a summary instead of the error, and trusts LLM output. | A |
| LG-6 | Med | Arbitrator lock has no depth count (nested release drops the outer lock) and no timeout. | A |
| LG-7 | Med | Goal evaluator passes goals with no matching keyword and expects state keys nobody supplies; the critic's score triggers recovery on retry count alone. | A |
| LG-8 | Med | Spec-driven engineer never validates the LLM's spec; file paths could contain `../`. | A |
| LG-9 | Med | **27 runtime/personal files are tracked in git:** `data/persona/*.md` (personal profile), 17 job state files, 5 eval-result files, `.bak` files. | **V** |
| LG-10 | Med | Packaging: `pyproject` and `requirements.txt` have drifted (LLM SDKs missing from the project dependencies); the `flexie` console script points at a module not in the package list; the PyInstaller spec omits many lazily imported packages and bundles with UPX (antivirus false positives). | A |
| LG-11 | Med | CI: Windows and Python 3.10 only; no type check, dependency audit, secret scan or build smoke test; coverage floor of 36% hides untested modules. | A |
| LG-12 | Med | Licensing: MIT project that bundles PyQt6 (GPL v3/commercial) — a legal question to confirm. | A |

**Recommendations**

| Module | Recommendation |
|---|---|
| Supervisor, durable runtime | Delete (the job system already provides resumable work) — or fix and wire in only if you want process supervision |
| LangGraph loop, unused agents/adapters, atomic actions | Delete (≈ 1,000 lines) and drop the LangGraph dependency tree |
| Recovery analyzer | Keep: remove `recovery/` from `.gitignore`, commit it, make it a singleton, pass the real error, validate the output |
| SDD engineer, goal evaluator, critic, arbitrator | Keep, but validate output and fix thresholds |
| Two gesture UIs (`flexie_web`, `vision`) | Keep one or move to a separate repository |

**Improvements:** split requirements into core/optional (heavy: chromadb, docker, vosk); add a lockfile; align `pyproject`; add the missing hidden imports; Python 3.10/3.11 matrix; secret scanning and a PyInstaller smoke test in CI; untrack runtime files and extend `.gitignore`.

---

## 4. Prioritised fix plan

### Phase 0 — This week (security, data loss, regressions) — all small

| # | Fix | Closes |
|---|---|---|
| 1 | Split clauses on `. ? ! \n & –`; add wipe/nuke/uninstall/shred/trash/overwrite as danger verbs | X-1 / SF-2 |
| 2 | Commit-on-write (or a held lock) in the shared SQLite connection | X-2 / MM-14 |
| 3 | Fix the memory load/save mismatch | MM-1 |
| 4 | Cache: add image path/provider/TTL to the key; never cache failure text | X-3 / LM-1/2 |
| 5 | File-tool deny-list (`.git`, `.env*`, tokens, MCP config, `core/`, `skills/`) + block secret reads | TL-1 |
| 6 | Cut the terminal allowlist to per-binary subcommands | TL-2 |
| 7 | Classify unknown wording/tools/MCP tools as *confirm* (deny by default) + add missing intent patterns | SF-1/4/5 |
| 8 | Gate the mail API endpoints; read-back + confirm before every send | SF-3 / EN-3 |
| 9 | Delete: confirm the exact resolved path, exact match required | EN-1/2 |
| 10 | Block `& < > ^ %` in `run_cmd`/developer engine (or drop `cmd /c`) | EN-4 |
| 11 | Bridge: Host + Origin checks; default origins = dashboard only; sign UI-bound UDP | UI-2/7/9 |
| 12 | Extension: fix the duplicate function; validate `CALL_API` endpoints | UI-1/12 |
| 13 | TTS: pass text via stdin; fix interrupt replay | UI-3/5 |
| 14 | `max_retries` + timeouts on all SDK clients; remove the 48 s sleep | LM-3/4 |
| 15 | Lazy-import the Gemini SDKs | LM-16 (−8.5 s startup) |
| 16 | `git rm --cached` runtime/personal files; un-ignore and commit `recovery/` | LG-1/9 |
| 17 | Collapse the three stray "phase(p1)" commits into one named commit | housekeeping |

### Phase 1 — Next 2 weeks (correctness quick wins)

- Stop lowercasing payloads in all small handlers; reminders (absolute time + correct confirmation); todo ordering; notification month-end and validation; converter (minus sign, plural units, ambiguity); tip/weather/dictionary regexes.
- Fix the four confident misroutes and add them to the eval; cap router input length.
- Email: one locked connection, UIDs, `BODY.PEEK[]`; indexes limited to user folders with size caps.
- MCP: default to confirm, drain stderr, ignore server-initiated messages, cap and label output.
- Memory: retention/TTL, redaction function, lock around the entries dictionary, `MemoryEngine` on WAL.
- Streaming guard (no duplicate text), Groq empty reply fallback, event bus tie-break.

### Phase 2 — Weeks 3–6 (structural)

- Approval redesign: request ids end to end, per-action tokens, lock, TTL.
- Replace wording-based classification with tool+argument "effect" metadata.
- FTS5 retrieval with ranking; vector prune and thresholds.
- Provider hedging, shared circuit breaker, a small dedicated routing model.
- Single Playwright worker thread; scheduler on `next_run` with persistence.
- Streaming TTS; background preflight.
- Re-run the orchestrator audit (the unaudited area).

### Phase 3 — Clean-up and release readiness

- Delete dead modules and the LangGraph dependency; split requirements; lockfile; fix packaging and the PyInstaller spec; expand CI (matrix, audit, secret scan, build smoke test); resolve the PyQt6/MIT licensing question.

---

## 5. Efficiency roadmap

| Area | Today | Target | How |
|---|---|---|---|
| Startup | ~17 s | ~8 s (estimate; remaining cost not yet profiled) | Lazy-import SDKs; background preflight/calibration; slim dependencies |
| Router | 1.8 ms; long text 0.2–0.9 s | < 0.5 ms; bounded | Input cap; keyword prefilter; compiled buckets |
| Worst-case LLM failure | 60–100 s | ≤ 10 s | No SDK retries, no sleeps, hedged fallback |
| Time to first spoken word | whole reply synthesised first | after the first chunk | Streaming TTS |
| Memory recall | whole-prompt substring; 22 ms at 20k entries | ranked, indexed, relevant | FTS5 + importance + recency |
| Email check | login per call, N+1 fetch | one connection, one fetch | Cached connection, UIDs |
| File/knowledge index | whole drives, hourly | user folders, incremental | Shared index with mtimes |
| Accuracy of routing | 100% on easy eval; ~10% confident misroutes on a realistic sample | ≥ 95% on a hard 150+ set | Bigger eval, fix patterns, route-dynamic tests |
| Observability | success-only telemetry; shuffled trace events | failures + honest latency | Record failures, event ordering, retention |

---

## 6. Definition of done (acceptance checks)

1. Every Phase 0 item has a regression test that **fails before** the fix and passes after.
2. Routing eval ≥ 150 cases, threshold 0.9 enforced in CI.
3. Startup time measured and recorded in the benchmark (target ≤ 10 s).
4. A short **live smoke test** with the real local model: a multi-step command, a "build a small app" request, a "fix my app" request, a specialist task, one voice approval, then `python -m core.telemetry.report`.
5. Re-audit of the orchestrator and a second pass over safety after Phase 0–1.

---

## Appendix A — What I verified myself

| Claim | Result |
|---|---|
| Clause splitter misses `. ? \n &` after a question | Reproduced (6 inputs) |
| Unmatched wording → read-only | Reproduced (5 inputs) |
| Blacklist bypasses / restricted-word false positives | Reproduced |
| Memory lost after restart | Reproduced (2 saved → 0 loaded) |
| Shared SQLite connection loses a thread's write | Reproduced |
| File jail accepts `.env`, `.git/hooks`, `core/safety.py`, `data/mcp_servers.json`, `skills/…` | Reproduced |
| Terminal allowlist contains `python`, `node`, `npx`, `pip`, `rg`, `robocopy` | Read |
| `run_cmd` accepts `echo … & del …`; delete confirm/target mismatch; 12 `logout()` calls | Read |
| Cache ignores image path; failure text stuck after reconnect | Reproduced |
| Hash/converter/reminder wrong results | Reproduced |
| Extension duplicate function; status endpoint argument; `CALL_API` URL; no Host check | Read |
| `recovery/` ignored and untracked; 27 tracked runtime/personal files | Reproduced |
| Router long-input cost; startup import breakdown; routing sample | Measured |

## Appendix B — Where to look (for developers)

| Module | Key locations |
|---|---|
| 1 Interfaces | `extension/sidebar.js` (duplicate `handleDomCommand`), `extension/background.js` (`CALL_API`), `interface/web_ui_bridge.py` (HTTP/WS handlers), `interface/voice.py` (SAPI path, neural fallback, recognizer), `interface/api_server.py` (status, mail endpoints, `_DEFAULT_ORIGINS`), `interface/web_ui.html` (toast/MCP innerHTML), `main.py`, `utils/helpers.py` (`is_online`), `utils/config.py` |
| 2 Routing | `core/router.py`, `core/hybrid_router.py`, `core/orchestrator.py`, `core/controller.py` |
| 4 Tools | `core/coding_tools.py`, `utils/path_jail.py`, `core/tool_registry.py`, `core/mcp_adapter.py`, `sandbox/executor.py`, `core/desktop_control.py`, `core/skills/`, `core/browser_and_comm_tools.py` |
| 5a Heavy | `engines/files.py`, `core/handlers/files.py`, `engines/email_engine.py`, `core/handlers/mail.py`, `engines/system.py`, `engines/developer.py`, `engines/browser.py`, `engines/knowledge.py`, `engines/clipboard_mgr.py`, `engines/automation.py` |
| 5b Utilities | `core/handlers/{hash_encoder,json_fmt,password,reminders,todo,notification,tip,converter,qrcode,text_tools,weather,dictionary,uuid,body_metrics,alarm,pomodoro}.py`, matching `engines/*` |
| 6 Safety | `core/safety.py`, `core/danger_gate.py`, `core/permission_system.py`, `core/plan_text.py` |
| 7 Memory | `core/memory_manager.py` (`_load`/`_row_for`, `search`), `core/memory_facade.py`, `core/context_memory.py`, `engines/memory*.py`, `core/vector_store.py`, `utils/sqlite_util.py` |
| 8 LLM | `core/brain.py` (cache, retries, streaming), `core/llm_providers.py`, `core/model_hub.py`, `core/inference/`, `core/telemetry/`, `core/traces/`, `core/event_bus/`, `evals/` |
| 9 Legacy | `.gitignore` (line `recovery/`), `supervisor/`, `runtime/`, `core/agent_loop.py`, `agents/`, `adapters/`, `pyproject.toml`, `requirements.txt`, `flexie.spec`, `.github/workflows/ci.yml` |

## Appendix C — Not covered or unconfirmed

- Orchestrator internals (queues, threads, watchdog/network loops, clarification flow, controller confirmation flow).
- Whether the ContextVar used for per-command usage attribution survives thread hand-offs.
- `chrome.sidePanel.open` needing a user gesture; whether extension `storage.local` is readable from content scripts; whether the popup overrides the side-panel action.
- Whether private-network browser protections block the DNS-rebinding path in some Chrome versions (treat as exploitable until tested).
- Gemini 2.5 "thinking" token undercounting; `<think>` text leaking from the local reasoning model.
- Live behaviour of voice, extension, browser/email automation, and any real LLM.
- PyQt6 (GPL) vs MIT licensing is a legal judgement.
