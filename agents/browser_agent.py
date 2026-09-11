from typing import Dict, Any
from agents.base import BaseAgent
from adapters.browser_adapter import LegacyBrowserAdapter
from engines.browser import BrowserEngine

class BrowserAgent(BaseAgent):
    """Browser agent receiving browser-automation task events and orchestrating through legacy adapters."""
    def __init__(self, browser_adapter: LegacyBrowserAdapter = None):
        super().__init__("browser", "Browser Automation Agent")
        self.adapter = browser_adapter or LegacyBrowserAdapter(BrowserEngine())

    def execute_task(self, payload: Dict[str, Any]) -> str:
        action = payload.get("action", "").lower().strip()
        target = payload.get("target", "").strip()
        value = payload.get("value", "").strip()

        self.logger.info(f"BrowserAgent executing action: {action} on {target}")

        if "navigate" in action or "open website" in action:
            return self.adapter.navigate(target)
        elif "click" in action:
            return self.adapter.click(target)
        elif "fill" in action or "type" in action:
            return self.adapter.fill(target, value)
        elif "summary" in action or "summarize" in action:
            # Need to pass orchestrator's brain
            from core.brain import Brain
            return self.adapter.get_summary(Brain())
        elif action == "multi_tab_research":
            from core.brain import Brain
            return self.adapter.engine.multi_tab_research(target or value or "latest technology news", Brain())
        else:
            return f"Action '{action}' is not supported by BrowserAgent."
