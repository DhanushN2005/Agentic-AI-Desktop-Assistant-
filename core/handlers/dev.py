import re

from engines.system import SystemCtrl


def handle_dev_build(orch, c):
    desc = re.sub(
        r"^(create a project for|build a project for|start a new project for|generate code for|code a project for|autonomous build for|create a project|build a project|start a new project|create an app for|build an app for|create a web app for|build a web app for)\s+",
        "",
        c,
        flags=re.IGNORECASE,
    ).strip()
    if not desc:
        orch.speak("What kind of project should I build for you?")
        desc = orch.voice.listen(timeout=10)

    if desc:
        res = orch.dev.autonomous_build(desc)
        orch.speak(res)
    return True


def handle_dev_explain(orch):
    orch.speak(orch.dev.explain_project())
    return True


def handle_briefing(orch):
    if orch.current_mode in ("focus", "minimal"):
        orch.speak("Standby.")
        return True
    orch.speak("Getting your daily briefing ready, Dhanush...")
    orch.speak(orch._get_briefing())
    return True


def handle_clipboard(orch):
    if orch.current_mode in ("focus", "minimal"):
        return True
    text = SystemCtrl.get_clipboard()
    if not text:
        orch.speak("Your clipboard is empty.")
    else:
        orch.speak("Analyzing your clipboard content...")
        summary = orch.brain.ask(f"Analyze/Summarize this text from my clipboard: {text[:2000]}")
        orch.speak(summary)
    return True


def handle_intel(orch, c):
    if orch.current_mode in ("focus", "minimal"):
        return True
    suggestion = orch.intel.analyze_context(c)
    if suggestion:
        orch.speak(suggestion)
    else:
        orch.speak("I'm monitoring your workflow and will suggest features when I see a perfect fit!")
    return True
