"""
Browser & Communication Tools Registry.

Registers Playwright browser automation and email communication tools into ToolRegistry,
enabling the AI agent loop, multi-step planner, and MCP systems to execute them safely.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.action_result import ActionResult
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec

logger = logging.getLogger("Flexie.BrowserCommTools")


def register_browser_and_comm_tools(registry: ToolRegistry, orch: Any) -> int:
    """Register browser automation and email communication tools. Returns count registered."""
    count = 0

    # 1. Browser Navigate
    def _browser_navigate(url: str) -> ActionResult:
        if not hasattr(orch, "browser") or not orch.browser:
            return ActionResult.fail("Browser engine is not available.", intent="browser_navigate")
        res = orch.browser.navigate(url)
        return ActionResult.ok(res, intent="browser_navigate", data={"url": url})

    registry.register(ToolSpec(
        name="browser_navigate",
        description="Navigate to a website URL in the browser",
        params=[ToolSchema(name="url", type="str", required=True, description="The full URL or domain to open")],
        permission=PermissionLevel.SAFE_ACTION,
        execute_fn=_browser_navigate,
        tags=["browser", "web"],
    ))
    count += 1

    # 2. Browser Search
    def _browser_search(query: str) -> ActionResult:
        if not hasattr(orch, "browser") or not orch.browser:
            return ActionResult.fail("Browser engine is not available.", intent="browser_search")
        res = orch.browser.search_in_browser(query)
        return ActionResult.ok(res, intent="browser_search", data={"query": query})

    registry.register(ToolSpec(
        name="browser_search",
        description="Perform a web search in Chrome and retrieve top results",
        params=[ToolSchema(name="query", type="str", required=True, description="Search term or question to look up")],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=_browser_search,
        tags=["browser", "search", "web"],
    ))
    count += 1

    # 3. Browser Click
    def _browser_click(selector_or_text: str) -> ActionResult:
        if not hasattr(orch, "browser") or not orch.browser:
            return ActionResult.fail("Browser engine is not available.", intent="browser_click")
        res = orch.browser.click_element(selector_or_text)
        return ActionResult.ok(res, intent="browser_click", data={"target": selector_or_text})

    registry.register(ToolSpec(
        name="browser_click",
        description="Click an interactive element, button, or link on the active webpage",
        params=[ToolSchema(name="selector_or_text", type="str", required=True, description="Visible text or CSS selector of the button/link")],
        permission=PermissionLevel.SAFE_ACTION,
        execute_fn=_browser_click,
        tags=["browser", "automation"],
    ))
    count += 1

    # 4. Browser Fill
    def _browser_fill(selector_or_label: str, value: str) -> ActionResult:
        if not hasattr(orch, "browser") or not orch.browser:
            return ActionResult.fail("Browser engine is not available.", intent="browser_fill")
        res = orch.browser.fill_field(selector_or_label, value)
        return ActionResult.ok(res, intent="browser_fill", data={"target": selector_or_label, "value": value})

    registry.register(ToolSpec(
        name="browser_fill",
        description="Fill an input field or text area on the active webpage",
        params=[
            ToolSchema(name="selector_or_label", type="str", required=True, description="Placeholder, label, or CSS selector of the field"),
            ToolSchema(name="value", type="str", required=True, description="Text value to enter into the field"),
        ],
        permission=PermissionLevel.SAFE_ACTION,
        execute_fn=_browser_fill,
        tags=["browser", "automation"],
    ))
    count += 1

    # 5. Browser Extract
    def _browser_extract(mode: str = "text") -> ActionResult:
        if not hasattr(orch, "browser") or not orch.browser:
            return ActionResult.fail("Browser engine is not available.", intent="browser_extract")
        res = orch.browser.extract_page_data(mode=mode)
        return ActionResult.ok(res, intent="browser_extract", data={"mode": mode})

    registry.register(ToolSpec(
        name="browser_extract",
        description="Extract visible text, links, or table data from the active webpage",
        params=[ToolSchema(name="mode", type="str", required=False, default="text", description="Extraction mode ('text', 'links', or 'tables')", enum=["text", "links", "tables"])],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=_browser_extract,
        tags=["browser", "extract"],
    ))
    count += 1

    # 6. Email Read Unread
    def _email_read_unread(count: int = 3) -> ActionResult:
        if not hasattr(orch, "email") or not orch.email:
            return ActionResult.fail("Email engine is not available.", intent="email_read_unread")
        detailed = orch.email.get_unread_emails_detailed(count=count)
        if detailed and "error" in detailed[0]:
            return ActionResult.fail(detailed[0]["error"], intent="email_read_unread")
        summary_lines = [f"• From {e.get('from')}: {e.get('subject')} ({e.get('preview', '')[:80]}...)" for e in detailed]
        return ActionResult.ok("\n".join(summary_lines) if summary_lines else "No unread emails.", intent="email_read_unread", data={"emails": detailed})

    registry.register(ToolSpec(
        name="email_read_unread",
        description="Check and read recent unread emails from the inbox",
        params=[ToolSchema(name="count", type="int", required=False, default=3, description="Number of emails to retrieve")],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=_email_read_unread,
        tags=["email", "communication"],
    ))
    count += 1

    # 7. Email Reply
    def _email_reply(to: str, body: str, subject: Optional[str] = None) -> ActionResult:
        if not hasattr(orch, "email") or not orch.email:
            return ActionResult.fail("Email engine is not available.", intent="email_reply")
        res = orch.email.reply_email(to=to, body=body, subject=subject)
        return ActionResult.ok(res, intent="email_reply", data={"to": to, "subject": subject})

    registry.register(ToolSpec(
        name="email_reply",
        description="Reply to an email with subject threading and webmail fallback",
        params=[
            ToolSchema(name="to", type="str", required=True, description="Recipient email address"),
            ToolSchema(name="body", type="str", required=True, description="The body content of the reply"),
            ToolSchema(name="subject", type="str", required=False, default=None, description="Original subject to thread into Re:"),
        ],
        permission=PermissionLevel.USER_CONFIRMATION,
        execute_fn=_email_reply,
        tags=["email", "communication"],
    ))
    count += 1

    # 8. Email Send
    def _email_send(to: str, subject: str, body: str) -> ActionResult:
        if not hasattr(orch, "email") or not orch.email:
            return ActionResult.fail("Email engine is not available.", intent="email_send")
        res = orch.email.send_email(to=to, subject=subject, body=body)
        return ActionResult.ok(res, intent="email_send", data={"to": to, "subject": subject})

    registry.register(ToolSpec(
        name="email_send",
        description="Compose and send a new email to a recipient",
        params=[
            ToolSchema(name="to", type="str", required=True, description="Recipient email address"),
            ToolSchema(name="subject", type="str", required=True, description="Email subject line"),
            ToolSchema(name="body", type="str", required=True, description="Email body content"),
        ],
        permission=PermissionLevel.USER_CONFIRMATION,
        execute_fn=_email_send,
        tags=["email", "communication"],
    ))
    count += 1

    logger.info("Registered %d browser and communication tools", count)
    return count
