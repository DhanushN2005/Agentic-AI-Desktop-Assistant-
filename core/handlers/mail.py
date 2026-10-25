"""
Mail handler — routes all email/mail intents to EmailEngine.

Supported intents (also registered in dispatcher.py):
  mail_check      — list unread inbox
  mail_read       — read a specific email (by number or sender)
  mail_send       — compose + send (AI-assisted or direct)
  mail_reply      — reply to email (AI-drafted or typed)
  mail_forward    — forward an email to another address
  mail_search     — search inbox by keyword
  mail_delete     — delete an email
  mail_archive    — archive an email
  mail_mark_read  — mark as read
  mail_draft      — save as draft
  mail_count      — how many unread emails
  mail_sent       — show sent emails
  mail_folders    — list available folders
  mail_summarize  — AI-powered inbox summary
  mail_compose    — AI-compose a new email
  gmail           — backward-compat alias for mail_check
"""

from __future__ import annotations
import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger("Flexie.MailHandler")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _email(orch):
    """Return the EmailEngine, or raise a clear error."""
    e = getattr(orch, "email", None)
    if e is None:
        raise AttributeError("EmailEngine not wired to orchestrator (orch.email is None).")
    return e


def _brain(orch):
    return getattr(orch, "brain", None)


def _extract_number(text: str) -> int | None:
    """Extract the first integer from a string (for 'read email 2')."""
    m = re.search(r"\b(\d+)\b", text)
    return int(m.group(1)) if m else None


def _extract_email_address(text: str) -> str:
    """Extract an email address from command text."""
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    return m.group(0) if m else ""


def _extract_after(text: str, *keywords) -> str:
    """Return text after the first matched keyword."""
    lower = text.lower()
    for kw in keywords:
        idx = lower.find(kw)
        if idx != -1:
            return text[idx + len(kw):].strip()
    return text.strip()


def _speak_emails(orch, emails: list[dict]) -> None:
    if not emails:
        orch.speak("No emails found.")
        return
    if "error" in emails[0]:
        orch.speak(emails[0]["error"])
        return
    for i, e in enumerate(emails, 1):
        orch.speak(
            f"Email {i}: From {e.get('from','?')}, "
            f"subject: {e.get('subject','(no subject)')}, "
            f"dated {e.get('date','?')}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Intent handlers
# ─────────────────────────────────────────────────────────────────────────────

def handle_mail_check(orch, c: str) -> bool:
    """List unread emails from inbox."""
    orch.send_to_ui("STATE", "PROCESSING")
    count_match = re.search(r"\b(\d+)\b", c)
    count = int(count_match.group(1)) if count_match else 5

    emails = _email(orch).get_unread_emails_detailed(count=count)
    if not emails or "error" in emails[0]:
        msg = emails[0].get("error", "No unread emails.") if emails else "No unread emails."
        orch.speak(msg)
        return True

    orch.speak(f"You have {len(emails)} unread email(s).")
    _speak_emails(orch, emails)
    # Send structured data to UI
    orch.send_to_ui("MAIL_INBOX", emails)
    return True


def handle_mail_count(orch, c: str) -> bool:
    """Say how many unread emails exist."""
    orch.send_to_ui("STATE", "PROCESSING")
    result = _email(orch).get_email_count()
    if "error" in result:
        orch.speak(result["error"])
    else:
        orch.speak(
            f"You have {result['unread']} unread email(s) out of {result['total']} total in your inbox."
        )
    return True


def handle_mail_read(orch, c: str) -> bool:
    """Read a specific email by index or sender keyword."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)

    idx = _extract_number(c)
    if idx and eng._last_inbox:
        email_obj = eng.get_email_by_index(idx)
        if email_obj:
            orch.speak(
                f"Email {idx} — from {email_obj['from']}, "
                f"subject: {email_obj['subject']}. "
                f"Body: {email_obj['body'][:500]}"
            )
            eng.mark_as_read(email_obj["id"])
            orch.send_to_ui("MAIL_READ", email_obj)
            return True

    # No index — search by sender/keyword
    keyword = re.sub(
        r"\b(read|open|show|email|mail|from|by|the|an?)\b", "", c, flags=re.I
    ).strip()
    if keyword:
        results = eng.search_emails(keyword, count=3)
        if results and "error" not in results[0]:
            e = results[0]
            orch.speak(
                f"Found email from {e['from']}, subject: {e['subject']}. "
                f"Body: {e['body'][:500]}"
            )
            eng.mark_as_read(e["id"])
            orch.send_to_ui("MAIL_READ", e)
            return True

    # Fallback — just load inbox and read first
    orch.speak("Loading inbox. Use 'read email 1' to read by number, or 'read email from [name]' to search.")
    return handle_mail_check(orch, c)


def handle_mail_send(orch, c: str) -> bool:
    """Compose and send an email. Supports AI-composed body."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    brain = _brain(orch)

    # Try to extract: 'send email to X about/saying Y'
    to_match = re.search(r"\bto\s+([\w.+@\-]+@[\w.-]+\.\w+|[\w\s]+?)(?:\s+(?:about|saying|with|subject|regarding|re:)\s+|\s*$)", c, re.I)
    to_addr = ""
    if to_match:
        raw_to = to_match.group(1).strip()
        to_addr = raw_to if "@" in raw_to else ""

    topic_match = re.search(r"\b(?:about|saying|regarding|re:?)\s+(.+)", c, re.I)
    topic = topic_match.group(1).strip() if topic_match else ""

    if not to_addr:
        to_addr = _extract_email_address(c)

    if not to_addr:
        orch.speak("Please specify the recipient's email address, for example: send email to user@example.com about meeting reschedule.")
        return True

    if brain and topic:
        orch.speak(f"Composing an AI-drafted email to {to_addr} about: {topic}…")
        composed = eng.ai_compose(brain, to_addr, topic)
        subject = composed.get("subject", f"Re: {topic}")
        body    = composed.get("body", topic)
        result  = eng.send_email(to=to_addr, subject=subject, body=body)
        orch.speak(result)
        orch.send_to_ui("MAIL_SENT", {"to": to_addr, "subject": subject, "body": body})
    elif topic:
        result = eng.send_email(to=to_addr, subject=f"Re: {topic}", body=topic)
        orch.speak(result)
    else:
        # No topic — open webmail compose
        url = eng.get_webmail_compose_url(to=to_addr)
        orch.speak(f"Opening Gmail compose window for {to_addr}.")
        import webbrowser
        webbrowser.open(url)

    return True


def handle_mail_reply(orch, c: str) -> bool:
    """Reply to the last fetched email or a specified one."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    brain = _brain(orch)

    idx = _extract_number(c)
    target = eng.get_email_by_index(idx) if idx else (eng._last_inbox[0] if eng._last_inbox else None)

    if not target:
        orch.speak("No email loaded to reply to. Check your inbox first with 'check mail'.")
        return True

    instruction = _extract_after(c, "reply with", "reply saying", "saying", "with")
    if not instruction or instruction.lower() in ("reply", ""):
        instruction = ""

    if brain:
        orch.speak(f"Drafting AI reply to {target['from']}…")
        body = eng.ai_draft_reply(brain, target, instruction)
    else:
        body = instruction or "Thanks for your email."

    result = eng.reply_email(to=_extract_email_address(target["from"]) or target["from"],
                             body=body, subject=target.get("subject"))
    orch.speak(result)
    orch.send_to_ui("MAIL_SENT", {"to": target["from"], "subject": f"Re: {target.get('subject','')}", "body": body})
    return True


def handle_mail_forward(orch, c: str) -> bool:
    """Forward an email to another address."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)

    to_addr = _extract_email_address(c)
    idx = _extract_number(c)
    target = eng.get_email_by_index(idx) if idx else (eng._last_inbox[0] if eng._last_inbox else None)

    if not target:
        orch.speak("No email to forward. Check your inbox first.")
        return True
    if not to_addr:
        orch.speak("Please specify the recipient's email address.")
        return True

    note_match = re.search(r"\b(?:note|saying|with note|adding)\s+(.+)", c, re.I)
    note = note_match.group(1).strip() if note_match else ""

    result = eng.forward_email(target["id"], to_addr, note)
    orch.speak(result)
    return True


def handle_mail_search(orch, c: str) -> bool:
    """Search inbox for a keyword."""
    orch.send_to_ui("STATE", "PROCESSING")
    query = re.sub(
        r"\b(search|find|look for|in|my|inbox|emails?|mails?)\b", "", c, flags=re.I
    ).strip()
    if not query:
        orch.speak("Please tell me what to search for, e.g. 'search emails about invoice'.")
        return True

    results = _email(orch).search_emails(query, count=5)
    if not results or "error" in results[0]:
        orch.speak(results[0].get("error", "No results.") if results else "No results.")
        return True

    orch.speak(f"Found {len(results)} email(s) matching '{query}'.")
    _speak_emails(orch, results)
    orch.send_to_ui("MAIL_SEARCH", {"query": query, "results": results})
    return True


def handle_mail_delete(orch, c: str) -> bool:
    """Delete an email by number."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    idx = _extract_number(c)
    target = eng.get_email_by_index(idx) if idx else (eng._last_inbox[0] if eng._last_inbox else None)
    if not target:
        orch.speak("No email selected. Use 'delete email 2' to specify one.")
        return True
    result = eng.delete_email(target["id"])
    orch.speak(result)
    return True


def handle_mail_archive(orch, c: str) -> bool:
    """Archive an email by number."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    idx = _extract_number(c)
    target = eng.get_email_by_index(idx) if idx else (eng._last_inbox[0] if eng._last_inbox else None)
    if not target:
        orch.speak("No email selected. Use 'archive email 2' to specify one.")
        return True
    result = eng.archive_email(target["id"])
    orch.speak(result)
    return True


def handle_mail_mark_read(orch, c: str) -> bool:
    """Mark an email as read."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    idx = _extract_number(c)
    target = eng.get_email_by_index(idx) if idx else (eng._last_inbox[0] if eng._last_inbox else None)
    if not target:
        orch.speak("No email selected.")
        return True
    result = eng.mark_as_read(target["id"])
    orch.speak(result)
    return True


def handle_mail_draft(orch, c: str) -> bool:
    """Save an email as a draft."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    brain = _brain(orch)

    to_addr = _extract_email_address(c)
    topic_match = re.search(r"\b(?:about|regarding|re:?)\s+(.+)", c, re.I)
    topic = topic_match.group(1).strip() if topic_match else "Draft"

    if brain and to_addr and topic:
        composed = eng.ai_compose(brain, to_addr, topic)
        result = eng.save_draft(to_addr, composed.get("subject", topic), composed.get("body", ""))
    elif to_addr:
        result = eng.save_draft(to_addr, f"Re: {topic}", topic)
    else:
        orch.speak("Please specify recipient and topic, e.g. 'draft email to user@example.com about project update'.")
        return True

    orch.speak(result)
    return True


def handle_mail_sent(orch, c: str) -> bool:
    """Show sent emails."""
    orch.send_to_ui("STATE", "PROCESSING")
    count_match = re.search(r"\b(\d+)\b", c)
    count = int(count_match.group(1)) if count_match else 5
    emails = _email(orch).get_sent_emails(count=count)
    if not emails or "error" in emails[0]:
        orch.speak(emails[0].get("error", "No sent emails.") if emails else "No sent emails.")
        return True
    orch.speak(f"Here are your {len(emails)} most recent sent email(s).")
    _speak_emails(orch, emails)
    orch.send_to_ui("MAIL_SENT_LIST", emails)
    return True


def handle_mail_folders(orch, c: str) -> bool:
    """List available email folders."""
    orch.send_to_ui("STATE", "PROCESSING")
    folders = _email(orch).get_folders()
    if not folders:
        orch.speak("Could not list folders. Check your email configuration.")
        return True
    orch.speak(f"Your mailbox has {len(folders)} folders: {', '.join(folders[:10])}.")
    return True


def handle_mail_summarize(orch, c: str) -> bool:
    """AI-powered summary of the inbox."""
    orch.send_to_ui("STATE", "PROCESSING")
    brain = _brain(orch)
    if not brain:
        return handle_mail_check(orch, c)

    orch.speak("Summarizing your inbox with AI…")
    summary = _email(orch).ai_summarize_inbox(brain, count=5)
    orch.speak(summary)
    orch.send_to_ui("MAIL_SUMMARY", {"summary": summary})
    return True


def handle_mail_compose(orch, c: str) -> bool:
    """AI-compose a new email and optionally send it."""
    orch.send_to_ui("STATE", "PROCESSING")
    eng = _email(orch)
    brain = _brain(orch)

    to_addr = _extract_email_address(c)
    topic_match = re.search(r"\b(?:about|regarding|re:?|compose|write|draft)\s+(.+)", c, re.I)
    topic = topic_match.group(1).strip() if topic_match else ""

    if not to_addr and not topic:
        orch.speak("Please specify a recipient and topic, e.g. 'compose email to user@example.com about Q4 results'.")
        return True

    if brain:
        composed = eng.ai_compose(brain, to_addr or "?", topic)
        orch.speak(
            f"Composed email. Subject: {composed['subject']}. "
            f"Body preview: {composed['body'][:120]}… "
            f"Say 'send it' to send or 'save as draft' to save."
        )
        # Cache for follow-up "send it" / "save as draft"
        orch.ctx.update(
            mail_pending={"to": to_addr, **composed}
        )
        orch.send_to_ui("MAIL_COMPOSE_PREVIEW", {"to": to_addr, **composed})
    else:
        url = eng.get_webmail_compose_url(to=to_addr, subject=topic)
        orch.speak(f"Opening Gmail composer for {to_addr}.")
        import webbrowser
        webbrowser.open(url)

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Main dispatcher called from core/handlers/dispatcher.py
# ─────────────────────────────────────────────────────────────────────────────

def handle_mail(orch, intent: str, c: str) -> bool:
    """Route mail intents to the appropriate sub-handler."""
    try:
        if intent in ("mail_check", "gmail", "check_mail", "inbox"):
            return handle_mail_check(orch, c)
        if intent == "mail_count":
            return handle_mail_count(orch, c)
        if intent == "mail_read":
            return handle_mail_read(orch, c)
        if intent == "mail_send":
            return handle_mail_send(orch, c)
        if intent == "mail_reply":
            return handle_mail_reply(orch, c)
        if intent == "mail_forward":
            return handle_mail_forward(orch, c)
        if intent == "mail_search":
            return handle_mail_search(orch, c)
        if intent == "mail_delete":
            return handle_mail_delete(orch, c)
        if intent == "mail_archive":
            return handle_mail_archive(orch, c)
        if intent == "mail_mark_read":
            return handle_mail_mark_read(orch, c)
        if intent == "mail_draft":
            return handle_mail_draft(orch, c)
        if intent == "mail_sent":
            return handle_mail_sent(orch, c)
        if intent == "mail_folders":
            return handle_mail_folders(orch, c)
        if intent == "mail_summarize":
            return handle_mail_summarize(orch, c)
        if intent == "mail_compose":
            return handle_mail_compose(orch, c)
        # Fallback
        return handle_mail_check(orch, c)
    except Exception as e:
        log.error("handle_mail(%s): %s", intent, e)
        orch.speak(f"Mail error: {e}")
        return False
