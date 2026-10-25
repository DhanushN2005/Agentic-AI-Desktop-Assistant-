"""
debug_swallow_harness.py — boot Flexie's core with DEBUG logging to surface
every newly-logged "Swallowed exception" site.

Does NOT start the mic loop, UI, or browser (those live in orchestrator.run()).
Constructs the orchestrator, exercises known-swallow-prone paths, cleans up.
"""
import io
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Capture all log output ──────────────────────────────────────────────────
buf = io.StringIO()
handler = logging.StreamHandler(buf)
handler.setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
root = logging.getLogger()
root.setLevel(logging.DEBUG)
root.addHandler(handler)
# silence noisy third-party loggers
for noisy in ("urllib3", "httpx", "asyncio", "websockets", "selenium", "duckduckgo_search", "ddgs", "groq"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def main():
    print("=== Booting Flexie orchestrator (no UI/mic/browser) ===", flush=True)

    from core.orchestrator import FlexieOrchestrator

    orch = FlexieOrchestrator()
    print("boot: OK\n", flush=True)

    # ── Exercise paths that previously swallowed exceptions ────────────────
    probes = []

    def probe(name, fn):
        try:
            fn()
            probes.append((name, "ok"))
        except Exception as e:  # noqa: BLE001 — probe must not die
            probes.append((name, f"PROBE RAISED {type(e).__name__}: {e}"))

    probe("config.reload", lambda: __import__("utils.config", fromlist=["Config"]).Config.reload())
    probe("memory_manager.search", lambda: orch.memory_manager.search("test", limit=3) if orch.memory_manager else None)
    probe("adaptive_router.save", lambda: orch.adaptive_router.save() if hasattr(orch.adaptive_router, "save") else None)
    probe("brain.provider_status", lambda: orch.brain.get_provider_status())
    probe("memory.get_context", lambda: orch.memory.get_context(limit=3))
    probe("telemetry.snapshot", lambda: __import__("core.telemetry", fromlist=["Telemetry"]).Telemetry().to_summary() if hasattr(__import__("core.telemetry", fromlist=["Telemetry"]).Telemetry(), "to_summary") else __import__("core.telemetry", fromlist=["Telemetry"]).Telemetry())
    probe("workflow_executor.verify", lambda: orch.workflow.verify_step("status", {}, "status", 0))
    probe("dispatcher.unknown_intent", lambda: __import__("core.handlers.dispatcher", fromlist=["dispatch_intent"]).dispatch_intent(orch, "definitely_not_an_intent", "hello world", True))
    probe("goal_planner.decompose", lambda: orch.goal_planner.decompose("open chrome and search cats") if orch.goal_planner else None)
    probe("tts_guard.dedupe", lambda: orch.tts_guard.should_speak("probe message"))
    probe("ctx.resolve", lambda: orch.ctx.resolve("open chrome"))
    probe("classifier.classify", lambda: orch.task_classifier.classify("status", False))
    probe("gatekeeper.classify", lambda: orch.workflow_gatekeeper.classify("open chrome"))

    print("=== Probes ===")
    for name, status in probes:
        print(f"  {name}: {status}")

    # ── Cleanup ─────────────────────────────────────────────────────────────
    try:
        orch.cleanup()
    except Exception as e:
        print(f"cleanup raised: {e}")
    # give daemon threads a moment
    threading.Event().wait(1.0)

    # ── Report swallowed exceptions ─────────────────────────────────────────
    out = buf.getvalue()
    with open("startup_debug.log", "w", encoding="utf-8") as f:
        f.write(out)

    swallowed = [
        line for line in out.splitlines()
        if "Swallowed exception" in line
    ]
    print(f"\n=== Swallowed exceptions: {len(swallowed)} ===")
    for line in swallowed:
        print(f"  {line}")

    # Also show warnings/errors that appeared during boot
    interesting = [
        line for line in out.splitlines()
        if line.startswith(("WARNING", "ERROR", "CRITICAL"))
        and "Swallowed" not in line
        and "GROQ_API_KEY" not in line
        and "GEMINI_API_KEY" not in line
    ]
    print(f"\n=== Other warnings/errors during boot: {len(interesting)} ===")
    for line in interesting[:25]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
