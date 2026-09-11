import logging
from engines.browser import BrowserEngine
from core.event_bus.bus import EventBus, Event

class LegacyBrowserAdapter:
    """Standardized adapter for the legacy BrowserEngine, mapping actions to the Event Bus."""
    def __init__(self, browser_engine: BrowserEngine):
        self.engine = browser_engine
        self.bus = EventBus()
        self.logger = logging.getLogger("BrowserAdapter")

    def navigate(self, url: str) -> str:
        self.bus.publish(Event("browser.navigate.start", {"url": url}, priority=1))
        res = self.engine.navigate(url)
        if "Navigated to" in res:
            self.bus.publish(Event("browser.navigate.success", {"url": url, "result": res}))
        else:
            self.bus.publish(Event("browser.navigate.failed", {"url": url, "error": res}, priority=0))
        return res

    def click(self, selector: str) -> str:
        self.bus.publish(Event("browser.click.start", {"selector": selector}, priority=1))
        res = self.engine.click_element(selector)
        if "Successfully clicked" in res:
            self.bus.publish(Event("browser.click.success", {"selector": selector, "result": res}))
        else:
            self.bus.publish(Event("browser.click.failed", {"selector": selector, "error": res}, priority=0))
        return res

    def fill(self, selector: str, value: str) -> str:
        self.bus.publish(Event("browser.fill.start", {"selector": selector, "value": value}, priority=1))
        res = self.engine.fill_field(selector, value)
        if "Successfully filled" in res:
            self.bus.publish(Event("browser.fill.success", {"selector": selector, "value": value, "result": res}))
        else:
            self.bus.publish(Event("browser.fill.failed", {"selector": selector, "value": value, "error": res}, priority=0))
        return res

    def get_summary(self, brain) -> str:
        self.bus.publish(Event("browser.summary.requested", {}, priority=2))
        return self.engine.get_summary(brain)

    def extract_text(self) -> str:
        return self.engine.extract_page_data("text")

    def close(self):
        self.engine.cleanup()
        self.bus.publish(Event("browser.closed", {}, priority=2))
