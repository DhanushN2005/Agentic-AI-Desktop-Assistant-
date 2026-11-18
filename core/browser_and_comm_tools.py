"""
Browser & Communication Tools Registry.

Registers Playwright browser automation and email communication tools into ToolRegistry,
enabling the AI agent loop, multi-step planner, and MCP systems to execute them safely.
"""
from __future__ import annotations

import logging
import re
from email.utils import parseaddr
from typing import Any

from core.action_result import ActionResult
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec

logger = logging.getLogger("Flexie.BrowserCommTools")

MAX_SUBJECT = 500
MAX_BODY = 50_000
MAX_RECIPIENTS = 20
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):(.*)$", re.DOTALL)
_HOST_PORT_REST_RE = re.compile(r"^\d{1,5}(?:[/?#].*)?$", re.DOTALL)
_ADDR_RE = re.compile(r"^[^@\s<>,;\"()\[\]\\:]+@[^@\s<>,;\"()\[\]\\:]+\.[^@\s<>,;\"()\[\]\\:]+$")
_ERROR_PREFIX_RE = re.compile(
    r"^\W*(error|failed|failure|could not|couldn't|unable|cannot|can't|exception|traceback|"
    r"email credentials not configured|browser engine is not|no browser)\b",
    re.IGNORECASE,
)


def validate_navigation_url(url: str) -> tuple[bool, str]:
    """Only http/https (or a bare domain / host:port) and about:blank may be opened."""
    if not isinstance(url, str) or not url.strip():
        return False, "URL is empty"
    u = url.strip()
    if len(u) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in u):
        return False, "URL is too long or contains control characters"
    if u.startswith(("\\\\", "//")):
        return False, "UNC / scheme-relative URLs are not allowed"
    m = _SCHEME_RE.match(u)
    if not m:
        return True, ""  # bare domain such as example.com/path
    scheme, rest = m.group(1).lower(), m.group(2)
    if scheme in ("http", "https"):
        return True, ""
    if u.lower() == "about:blank":
        return True, ""
    if (scheme not in ("javascript", "data", "file", "chrome", "about", "vbscript", "blob")
            and _HOST_PORT_REST_RE.match(rest)):
        return True, ""  # host:port
    return False, f"URL scheme '{scheme}:' is not allowed (only http/https)"


def validate_recipients(to: str, allow_multiple: bool = False) -> tuple[str | None, str]:
    """Return (normalised address list, '') or (None, error). Rejects header injection."""
    if not isinstance(to, str) or not to.strip():
        return None, "recipient is empty"
    if any(c in to for c in "\r\n\x00"):
        return None, "recipient must not contain line breaks"
    if not allow_multiple and ("," in to or ";" in to):
        return None, "exactly one recipient is allowed (multiple recipients need allow_multiple=true)"
    parts = [p for p in re.split(r"[;,]", to) if p.strip()] if allow_multiple else [to]
    if not parts or len(parts) > MAX_RECIPIENTS:
        return None, f"between 1 and {MAX_RECIPIENTS} recipients are allowed"
    clean = []
    for part in parts:
        _name, addr = parseaddr(part.strip())
        if not addr or not _ADDR_RE.match(addr) or len(addr) > 254:
            return None, f"invalid email address: {part.strip()[:80]!r}"
        clean.append(addr)
    return ", ".join(clean), ""


def _clean_header(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"[\r\n\x00]+", " ", text)[:MAX_SUBJECT]


def _engine_failed(res: Any) -> str | None:
    """Error text when an engine reply is an error (error-word prefix string / dict with 'error')."""
    if isinstance(res, dict) and res.get("error"):
        return str(res["error"])[:500]
    if isinstance(res, str) and _ERROR_PREFIX_RE.match(res):
        return res[:500]
    return None


def _redact(text: Any, secret: str) -> str:
    text = text if isinstance(text, str) else str(text)
    return text.replace(secret, "[redacted]") if len(secret) >= 3 else text


def register_browser_and_comm_tools(registry: ToolRegistry, orch: Any) -> int:
    """Register browser automation and email communication tools. Returns count registered."""
    count = 0

    # 1. Browser Navigate
    def _browser_navigate(url: str) -> ActionResult:
        if not hasattr(orch, "browser") or not orch.browser:
            return ActionResult.fail("Browser engine is not available.", intent="browser_navigate")
        ok, why = validate_navigation_url(url)
        if not ok:
            return ActionResult.fail(f"Blocked URL: {why}", intent="browser_navigate", data={"url": url[:200]})
        res = orch.browser.navigate(url.strip())
        err = _engine_failed(res)
        if err:
            return ActionResult.fail(err, intent="browser_navigate", data={"url": url})
        return ActionResult.ok(res, intent="browser_navigate", data={"url": url})

    registry.register(ToolSpec(
        name="browser_navigate", capabilities=["network:fetch"],
        description="Navigate to a website URL in the browser",
        params=[ToolSchema(name="url", type="str", required=True, description="The http(s) URL or domain to open", max_length=2048)],
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
        err = _engine_failed(res)
        if err:
            return ActionResult.fail(err, intent="browser_search", data={"query": query})
        return ActionResult.ok(res, intent="browser_search", data={"query": query})

    registry.register(ToolSpec(
        name="browser_search", idempotent=True, capabilities=["network:fetch"],
        description="Perform a web search in Chrome and retrieve top results",
        params=[ToolSchema(name="query", type="str", required=True, description="Search term or question to look up", max_length=500)],
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
        err = _engine_failed(res)
        if err:
            return ActionResult.fail(err, intent="browser_click", data={"target": selector_or_text})
        return ActionResult.ok(res, intent="browser_click", data={"target": selector_or_text})

    registry.register(ToolSpec(
        name="browser_click", capabilities=["network:fetch"],
        description="Click an interactive element, button, or link on the active webpage",
        params=[ToolSchema(name="selector_or_text", type="str", required=True, description="Visible text or CSS selector of the button/link", max_length=500)],
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
        res = _redact(res, value)  # never echo what was typed (passwords, tokens)
        err = _engine_failed(res)
        data = {"target": selector_or_label, "value_length": len(value)}
        if err:
            return ActionResult.fail(err, intent="browser_fill", data=data)
        return ActionResult.ok(res, intent="browser_fill", data=data)

    registry.register(ToolSpec(
        name="browser_fill", capabilities=["network:fetch"],
        description="Fill an input field or text area on the active webpage",
        params=[
            ToolSchema(name="selector_or_label", type="str", required=True, description="Placeholder, label, or CSS selector of the field", max_length=500),
            ToolSchema(name="value", type="str", required=True, description="Text value to enter into the field", max_length=10_000),
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
        name="browser_extract", idempotent=True, capabilities=["network:fetch"],
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
        count = max(1, min(50, int(count)))
        detailed = orch.email.get_unread_emails_detailed(count=count)
        if detailed and "error" in detailed[0]:
            return ActionResult.fail(detailed[0]["error"], intent="email_read_unread")
        summary_lines = [f"• From {e.get('from')}: {e.get('subject')} ({e.get('preview', '')[:80]}...)" for e in detailed]
        return ActionResult.ok("\n".join(summary_lines) if summary_lines else "No unread emails.", intent="email_read_unread", data={"emails": detailed})

    registry.register(ToolSpec(
        name="email_read_unread", idempotent=True, capabilities=["network:fetch"],
        description="Check and read recent unread emails from the inbox",
        params=[ToolSchema(name="count", type="int", required=False, default=3, description="Number of emails to retrieve (1-50)", minimum=1, maximum=50)],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=_email_read_unread,
        tags=["email", "communication"],
    ))
    count += 1

    # 7. Email Reply
    def _email_reply(to: str, body: str, subject: str | None = None, allow_multiple: bool = False) -> ActionResult:
        if not hasattr(orch, "email") or not orch.email:
            return ActionResult.fail("Email engine is not available.", intent="email_reply")
        addr, why = validate_recipients(to, allow_multiple)
        if addr is None:
            return ActionResult.fail(f"Invalid recipient: {why}", intent="email_reply")
        if len(body) > MAX_BODY:
            return ActionResult.fail(f"Body is too long (max {MAX_BODY} chars)", intent="email_reply")
        subject = _clean_header(subject)
        res = orch.email.reply_email(to=addr, body=body, subject=subject)
        err = _engine_failed(res)
        if err:
            return ActionResult.fail(err, intent="email_reply", data={"to": addr, "subject": subject})
        return ActionResult.ok(res, intent="email_reply", data={"to": addr, "subject": subject})

    registry.register(ToolSpec(
        name="email_reply", capabilities=["network:fetch"],
        description="Reply to an email with subject threading and webmail fallback",
        params=[
            ToolSchema(name="to", type="str", required=True, description="Recipient email address (one)", max_length=320),
            ToolSchema(name="body", type="str", required=True, description="The body content of the reply", max_length=MAX_BODY),
            ToolSchema(name="subject", type="str", required=False, default=None, description="Original subject to thread into Re:", max_length=MAX_SUBJECT),
            ToolSchema(name="allow_multiple", type="bool", required=False, default=False, description="Explicitly allow several comma-separated recipients"),
        ],
        permission=PermissionLevel.USER_CONFIRMATION,
        execute_fn=_email_reply,
        tags=["email", "communication"],
        idempotent=False,
    ))
    count += 1

    # 8. Email Send
    def _email_send(to: str, subject: str, body: str, allow_multiple: bool = False) -> ActionResult:
        if not hasattr(orch, "email") or not orch.email:
            return ActionResult.fail("Email engine is not available.", intent="email_send")
        addr, why = validate_recipients(to, allow_multiple)
        if addr is None:
            return ActionResult.fail(f"Invalid recipient: {why}", intent="email_send")
        if len(body) > MAX_BODY:
            return ActionResult.fail(f"Body is too long (max {MAX_BODY} chars)", intent="email_send")
        subject = _clean_header(subject) or ""
        res = orch.email.send_email(to=addr, subject=subject, body=body)
        err = _engine_failed(res)
        if err:
            return ActionResult.fail(err, intent="email_send", data={"to": addr, "subject": subject})
        return ActionResult.ok(res, intent="email_send", data={"to": addr, "subject": subject})

    registry.register(ToolSpec(
        name="email_send", capabilities=["network:fetch"],
        description="Compose and send a new email to a recipient",
        params=[
            ToolSchema(name="to", type="str", required=True, description="Recipient email address (one)", max_length=320),
            ToolSchema(name="subject", type="str", required=True, description="Email subject line", max_length=MAX_SUBJECT),
            ToolSchema(name="body", type="str", required=True, description="Email body content", max_length=MAX_BODY),
            ToolSchema(name="allow_multiple", type="bool", required=False, default=False, description="Explicitly allow several comma-separated recipients"),
        ],
        permission=PermissionLevel.USER_CONFIRMATION,
        execute_fn=_email_send,
        tags=["email", "communication"],
        idempotent=False,
    ))
    count += 1

    logger.info("Registered %d browser and communication tools", count)
    return count
