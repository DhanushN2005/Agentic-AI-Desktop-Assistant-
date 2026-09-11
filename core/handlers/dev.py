import re

from engines.system import SystemCtrl


def handle_dev_build(orch, c):
    desc = re.sub(r"^(create a project for|build a project for|start a new project for|generate code for|code a project for|autonomous build for|create a project|build a project|start a new project)\s+", "", c).strip()
    if not desc:
        orch.speak("What kind of project should I build for you?")
        desc = orch.voice.listen(timeout=10)

    if desc:
        orch.speak(orch.dev.autonomous_build(desc))
    return True


def handle_dev_explain(orch):
    orch.speak(orch.dev.explain_project())
    return True


def handle_briefing(orch):
    orch.speak("Getting your daily briefing ready, Dhanush...")
    orch.speak(orch._get_briefing())
    return True


def handle_clipboard(orch):
    text = SystemCtrl.get_clipboard()
    if not text:
        orch.speak("Your clipboard is empty.")
    else:
        orch.speak("Analyzing your clipboard content...")
        summary = orch.brain.ask(f"Analyze/Summarize this text from my clipboard: {text[:2000]}")
        orch.speak(summary)
    return True


def handle_intel(orch, c):
    suggestion = orch.intel.analyze_context(c)
    if suggestion:
        orch.speak(suggestion)
    else:
        orch.speak("I'm monitoring your workflow and will suggest features when I see a perfect fit!")
    return True
