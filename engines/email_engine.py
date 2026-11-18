import atexit
import email
import email.header
import imaplib
import logging
import re
import smtplib
import threading
import time
from contextlib import contextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, parseaddr

from utils.config import Config

log = logging.getLogger("Flexie.Email")


_ADDR_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}$")


def validate_address(raw: str) -> str:
    """Return a clean ASCII address or '' if the input is odd/lookalike/multi-recipient."""
    raw = (raw or "").strip()
    if not raw or re.search(r"[\r\n\x00,;]", raw):
        return ""
    _name, addr = parseaddr(raw)
    addr = addr.strip()
    if raw.count("@") != 1 or not addr or not addr.isascii() or not _ADDR_RE.match(addr):
        return ""
    return addr
    return addr


def _decode_header(raw: str) -> str:
    """Safely decode encoded email header strings."""
    try:
        parts = email.header.decode_header(raw or "")
        decoded = []
        for chunk, charset in parts:
            if isinstance(chunk, bytes):
                decoded.append(chunk.decode(charset or "utf-8", errors="ignore"))
            else:
                decoded.append(str(chunk))
        return "".join(decoded)
    except Exception:
        return str(raw)


def _extract_body(msg) -> str:
    """Extract the best plain-text body from an email.message.Message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = part.get("Content-Disposition", "")
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="ignore")
                    break
                except Exception as _e:
                    logging.debug("[engines/email_engine.py:42] Swallowed exception: %s: %s", type(_e).__name__, _e)
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="ignore")
        except Exception as _e:
            logging.debug("[engines/email_engine.py:48] Swallowed exception: %s: %s", type(_e).__name__, _e)
    return body.strip()


_IMAP_HOST = "imap.gmail.com"
_imap_lock = threading.RLock()
_cached_imap = None
_cached_imap_time = 0.0
_IDLE_PROBE_SECS = 30.0


def _new_connection():
    """Open and authenticate a fresh IMAP connection (patched in tests)."""
    m = imaplib.IMAP4_SSL(_IMAP_HOST, timeout=30)
    m.login(Config.EMAIL_ADDRESS, Config.EMAIL_PASSWORD)
    return m


def _quote_mailbox(name: str) -> str:
    """Quote a mailbox name for IMAP (idempotent for already-quoted names)."""
    name = (name or "INBOX").strip()
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    name = re.sub(r"[\r\n\x00]", "", name)
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _quote_search(text: str) -> str:
    """Escape user text for use inside an IMAP quoted string."""
    text = re.sub(r"[\r\n\x00]", " ", text or "").strip()
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_reset() -> None:
    """Drop the cached connection (best-effort close)."""
    global _cached_imap
    with _imap_lock:
        m, _cached_imap = _cached_imap, None
    if m is not None:
        try:
            m.logout()
        except Exception as _e:
            logging.debug("imap logout during reset: %s", _e)


def close_connection() -> None:
    """Close the shared IMAP connection (called at shutdown)."""
    _imap_reset()


atexit.register(close_connection)


def _imap_connect():
    """Return the ONE cached, authenticated connection (reconnects when stale)."""
    global _cached_imap, _cached_imap_time
    if not (Config.EMAIL_ADDRESS and Config.EMAIL_PASSWORD):
        raise RuntimeError("Email credentials not configured (EMAIL_ADDRESS / EMAIL_PASSWORD).")
    with _imap_lock:
        now = time.time()
        if _cached_imap is not None:
            if now - _cached_imap_time < _IDLE_PROBE_SECS:
                _cached_imap_time = now
                return _cached_imap
            try:
                status, _ = _cached_imap.noop()
                if status == "OK":
                    _cached_imap_time = now
                    return _cached_imap
            except Exception as _e:
                logging.debug("imap noop failed, reconnecting: %s", _e)
            _imap_reset()
        _cached_imap = _new_connection()
        _cached_imap_time = now
        return _cached_imap


@contextmanager
def _imap_session(folder: str = "INBOX", readonly: bool = True):
    """Serialise access to the shared connection and select ``folder`` (status checked).

    The connection is kept open on success; on any error it is discarded so the
    next call reconnects.  Callers must NOT call logout().
    """
    with _imap_lock:
        m = _imap_connect()
        try:
            typ, _data = m.select(_quote_mailbox(folder), readonly)
            if typ != "OK":
                raise RuntimeError(f"Could not open folder {folder}")
            yield m
        except Exception:
            _imap_reset()
            raise


def _uid_str(email_id) -> str:
    uid = str(email_id).strip()
    if not uid.isdigit():
        raise ValueError(f"Invalid email id: {email_id!r}")
    return uid


def _uid_search(m, *criteria) -> list[int]:
    typ, data = m.uid("SEARCH", None, *criteria)
    if typ != "OK":
        raise RuntimeError("IMAP search failed")
    raw = data[0] if data and data[0] else b""
    return sorted(int(x) for x in raw.split())  # numeric order: newest = highest UID


def _fetch_messages(m, uids: list[int], with_body: bool = True) -> list[dict]:
    """ONE batched UID FETCH (BODY.PEEK so nothing is marked read); returns dicts oldest->newest."""
    if not uids:
        return []
    spec = "(FLAGS BODY.PEEK[])" if with_body else "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])"
    typ, data = m.uid("FETCH", ",".join(str(u) for u in uids), spec)
    if typ != "OK":
        raise RuntimeError("IMAP fetch failed")
    out: dict[int, dict] = {}
    for item in data or []:
        if not isinstance(item, tuple):
            continue
        meta = item[0].decode("utf-8", "ignore") if isinstance(item[0], bytes) else str(item[0])
        mu = re.search(r"UID (\d+)", meta)
        if not mu:
            continue
        uid = int(mu.group(1))
        mf = re.search(r"FLAGS \(([^)]*)\)", meta)
        flags = mf.group(1) if mf else ""
        msg = email.message_from_bytes(item[1])
        body = _extract_body(msg) if with_body else ""
        out[uid] = {
            "id": str(uid),
            "from": _decode_header(msg.get("From", "")),
            "to": _decode_header(msg.get("To", "")),
            "subject": _decode_header(msg.get("Subject", "(no subject)")),
            "date": msg.get("Date", ""),
            "preview": body[:300],
            "body": body,
            "read": "\\Seen" in flags,
        }
    return [out[u] for u in sorted(out)]


class EmailEngine:
    def __init__(self):
        self.addr = Config.EMAIL_ADDRESS
        self.pwd  = Config.EMAIL_PASSWORD
        # In-session cache for last-fetched emails so handlers can reference "email 2"
        self._last_inbox: list[dict] = []

    def close(self) -> None:
        close_connection()

    def _is_configured(self) -> bool:
        return bool(self.addr and self.pwd)

    # ─────────────────────────────────────────────────────────────────
    # READ
    # ─────────────────────────────────────────────────────────────────

    def get_unread_emails(self, count: int = 5) -> list[str]:
        detailed = self.get_unread_emails_detailed(count=count)
        if not detailed:
            return ["No unread emails."]
        if "error" in detailed[0]:
            return [detailed[0]["error"]]
        return [f"From {e['from']}: {e['subject']}" for e in detailed]

    def get_unread_emails_detailed(self, count: int = 5) -> list[dict]:
        """Fetch unread emails (newest by UID) without marking them read."""
        if not self._is_configured():
            return [{"error": "Email credentials not configured."}]
        try:
            with _imap_session("INBOX") as m:
                uids = _uid_search(m, "UNSEEN")[-count:]
                results = _fetch_messages(m, uids)
            for r in results:
                r["read"] = False
            self._last_inbox = results
            return results
        except Exception as e:
            log.error("get_unread_emails_detailed: %s", e)
            return [{"error": f"Could not read inbox: {e}"}]

    def get_all_emails(self, count: int = 10, folder: str = "INBOX") -> list[dict]:
        """Fetch the N most recent emails from any folder."""
        if not self._is_configured():
            return [{"error": "Email credentials not configured."}]
        try:
            with _imap_session(folder) as m:
                uids = _uid_search(m, "ALL")[-count:]
                results = _fetch_messages(m, uids)
            self._last_inbox = results
            return results
        except Exception as e:
            log.error("get_all_emails: %s", e)
            return [{"error": f"Could not read folder: {e}"}]

    def get_email_by_index(self, idx: int) -> dict | None:
        """Return a cached email from the last fetch (1-based index)."""
        if 1 <= idx <= len(self._last_inbox):
            return self._last_inbox[idx - 1]
        return None

    def search_emails(self, query: str, count: int = 10) -> list[dict]:
        """Search inbox by subject, sender or body with ONE query and ONE batched fetch."""
        if not self._is_configured():
            return [{"error": "Email credentials not configured."}]
        q = (query or "").strip()
        if not q:
            return [{"error": "Search failed: empty query."}]
        try:
            with _imap_session("INBOX") as m:
                qq = _quote_search(q)
                uids = _uid_search(m, "OR", "OR", "SUBJECT", qq, "FROM", qq, "BODY", qq)[-count:]
                results = _fetch_messages(m, uids)
            for r in results:
                r["preview"] = r["body"][:200]
            return results
        except Exception as e:
            log.error("search_emails: %s", e)
            return [{"error": f"Search failed: {e}"}]

    def get_sent_emails(self, count: int = 5) -> list[dict]:
        """Fetch recently sent emails."""
        folders = ["[Gmail]/Sent Mail", "Sent", "Sent Messages"]
        for folder in folders:
            try:
                result = self.get_all_emails(count=count, folder=folder)
                if result and "error" not in result[0]:
                    return result
            except Exception:
                continue
        return [{"error": "Could not find Sent folder."}]

    def get_email_count(self) -> dict:
        """Return unread and total count for inbox."""
        if not self._is_configured():
            return {"error": "Email credentials not configured."}
        try:
            with _imap_session("INBOX") as m:
                typ, data = m.status(_quote_mailbox("INBOX"), "(MESSAGES UNSEEN)")
                if typ != "OK":
                    raise RuntimeError("STATUS failed")
                text = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
                total = int(re.search(r"MESSAGES (\d+)", text).group(1))
                unread = int(re.search(r"UNSEEN (\d+)", text).group(1))
            return {"unread": unread, "total": total}
        except Exception as e:
            return {"error": str(e)}

    def get_folders(self) -> list[str]:
        """List all IMAP mailbox folders."""
        if not self._is_configured():
            return []
        try:
            with _imap_lock:
                m = _imap_connect()
                try:
                    _, folders = m.list()
                except Exception:
                    _imap_reset()
                    raise
            names = []
            for f in folders or []:
                if not f:
                    continue
                line = f.decode() if isinstance(f, bytes) else str(f)
                mm = re.match(r'\((?P<fl>.*?)\)\s+(?:"(?P<d>[^"]*)"|NIL)\s+(?P<n>.+)$', line)
                if mm:
                    names.append(mm.group("n").strip().strip('"'))
            return names
        except Exception as e:
            log.error("get_folders: %s", e)
            return []

    # ─────────────────────────────────────────────────────────────────
    # STATUS CHANGES (all keyed by UID, never by shifting sequence numbers)
    # ─────────────────────────────────────────────────────────────────

    def mark_as_read(self, email_id: str) -> str:
        """Mark a specific email as read by IMAP UID."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            uid = _uid_str(email_id)
            with _imap_session("INBOX", readonly=False) as m:
                typ, _ = m.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                if typ != "OK":
                    return "Failed to mark as read."
            return f"Email {uid} marked as read."
        except Exception as e:
            return f"Failed to mark as read: {e}"

    def mark_as_unread(self, email_id: str) -> str:
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            uid = _uid_str(email_id)
            with _imap_session("INBOX", readonly=False) as m:
                typ, _ = m.uid("STORE", uid, "-FLAGS", "(\\Seen)")
                if typ != "OK":
                    return "Failed to mark as unread."
            return f"Email {uid} marked as unread."
        except Exception as e:
            return f"Failed: {e}"

    def _move_uid(self, m, uid: str, dest: str) -> str | None:
        """COPY then flag \\Deleted then UID EXPUNGE. Returns an error string or None."""
        typ, _ = m.uid("COPY", uid, _quote_mailbox(dest))
        if typ != "OK":
            return f"copy to {dest} failed, original left untouched"
        typ, _ = m.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
        if typ != "OK":
            return "could not flag the original for removal"
        caps = getattr(m, "capabilities", ()) or ()
        if "UIDPLUS" in {str(c).upper() for c in caps}:
            m.uid("EXPUNGE", uid)  # removes only this message
        else:
            log.warning("IMAP server lacks UIDPLUS; message %s flagged but not expunged", uid)
        return None

    def delete_email(self, email_id: str) -> str:
        """Copy to Trash (Gmail); flag/expunge the original only if the copy succeeded."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            uid = _uid_str(email_id)
            with _imap_session("INBOX", readonly=False) as m:
                err = self._move_uid(m, uid, "[Gmail]/Trash")
            return f"Failed to delete: {err}" if err else f"Email {uid} deleted."
        except Exception as e:
            return f"Failed to delete: {e}"

    def archive_email(self, email_id: str) -> str:
        """Move email to Gmail archive ([Gmail]/All Mail) and remove from Inbox."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            uid = _uid_str(email_id)
            with _imap_session("INBOX", readonly=False) as m:
                err = self._move_uid(m, uid, "[Gmail]/All Mail")
            return f"Failed to archive: {err}" if err else f"Email {uid} archived."
        except Exception as e:
            return f"Failed to archive: {e}"

    def move_to_folder(self, email_id: str, folder: str) -> str:
        """Move email to the specified IMAP folder."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            uid = _uid_str(email_id)
            with _imap_session("INBOX", readonly=False) as m:
                err = self._move_uid(m, uid, folder)
            return f"Failed to move: {err}" if err else f"Email moved to {folder}."
        except Exception as e:
            return f"Failed to move: {e}"

    # ─────────────────────────────────────────────────────────────────
    # SEND / COMPOSE / DRAFT
    # ─────────────────────────────────────────────────────────────────

    def send_email(self, to: str, subject: str, body: str) -> str:
        if not self._is_configured():
            return "Email credentials not configured."
        to = validate_address(to)
        if not to:
            return "Failed to send: the recipient address is not valid."
        subject = re.sub(r"[\r\n]+", " ", subject or "")
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.addr
            msg["To"] = to
            msg["Date"] = formatdate(localtime=True)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                srv.login(self.addr, self.pwd)
                srv.send_message(msg)
            return f"Email sent to {to}."
        except Exception as e:
            log.error("send_email: %s", e)
            return f"Failed to send: {e}"

    def send_email_html(self, to: str, subject: str, body_text: str, body_html: str) -> str:
        """Send a multi-part email with both plain text and HTML."""
        if not self._is_configured():
            return "Email credentials not configured."
        to = validate_address(to)
        if not to:
            return "Failed to send: the recipient address is not valid."
        subject = re.sub(r"[\r\n]+", " ", subject or "")
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.addr
            msg["To"] = to
            msg["Date"] = formatdate(localtime=True)
            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                srv.login(self.addr, self.pwd)
                srv.send_message(msg)
            return f"Email sent to {to}."
        except Exception as e:
            return f"Failed to send: {e}"

    def reply_email(self, to: str, body: str, subject: str | None = None) -> str:
        """Reply with a Re: subject line, falling back to webmail if unconfigured."""
        if not subject:
            subject = "Re: Your message"
        elif not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        if not self._is_configured():
            url = self.get_webmail_compose_url(to=to, subject=subject, body=body)
            import webbrowser
            try:
                webbrowser.open(url)
                return f"Credentials not set — opened Gmail webmail to reply to {to}."
            except Exception:
                return f"Credentials not configured. Reply to {to} manually."
        return self.send_email(to=to, subject=subject, body=body)

    def forward_email(self, email_id: str, to: str, note: str = "") -> str:
        """Forward an existing email (by last-inbox index or IMAP id) to another address."""
        # Try to find the email in cache first
        target = None
        for e in self._last_inbox:
            if e.get("id") == email_id:
                target = e
                break
        if not target:
            return f"Email {email_id} not found in last fetch. Refresh inbox first."
        fwd_subject = f"Fwd: {target.get('subject','')}"
        fwd_body = f"{note}\n\n---------- Forwarded message ----------\nFrom: {target.get('from','')}\nDate: {target.get('date','')}\nSubject: {target.get('subject','')}\n\n{target.get('body','')}"
        return self.send_email(to=to, subject=fwd_subject, body=fwd_body)

    def save_draft(self, to: str, subject: str, body: str) -> str:
        """Save a draft to Gmail Drafts folder via IMAP APPEND."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.addr
            msg["To"] = to
            msg["Date"] = formatdate(localtime=True)
            with _imap_lock:
                m = _imap_connect()
                try:
                    typ, _ = m.append(_quote_mailbox("[Gmail]/Drafts"), "(\\Draft)",
                                      imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                except Exception:
                    _imap_reset()
                    raise
            if typ != "OK":
                return "Failed to save draft."
            return f"Draft saved: '{subject}' to {to}."
        except Exception as e:
            return f"Failed to save draft: {e}"

    # ─────────────────────────────────────────────────────────────────
    # WEBMAIL FALLBACK
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_webmail_compose_url(to: str = "", subject: str = "", body: str = "") -> str:
        """Construct a Gmail web composer URL for browser fallback."""
        import urllib.parse
        params = {"view": "cm", "fs": "1"}
        if to:
            params["to"] = to
        if subject:
            params["su"] = subject
        if body:
            params["body"] = body[:2000]
        return f"https://mail.google.com/mail/?{urllib.parse.urlencode(params)}"

    # ─────────────────────────────────────────────────────────────────
    # AI HELPERS
    # ─────────────────────────────────────────────────────────────────

    def ai_summarize_inbox(self, brain, count: int = 5) -> str:
        """Use the AI brain to summarize unread emails."""
        emails = self.get_unread_emails_detailed(count=count)
        if not emails or "error" in emails[0]:
            return emails[0].get("error", "No emails.") if emails else "No emails."
        lines = []
        for i, e in enumerate(emails, 1):
            lines.append(f"{i}. From: {e['from']}\n   Subject: {e['subject']}\n   Preview: {e['preview'][:150]}")
        prompt = (
            f"Summarize these {len(emails)} unread emails concisely — "
            f"one sentence each, note any urgent items:\n\n" + "\n\n".join(lines)
        )
        try:
            return brain.ask(prompt)
        except Exception as e:
            return "\n".join(lines)

    def ai_draft_reply(self, brain, original: dict, instruction: str = "") -> str:
        """Draft a reply to an email using the AI brain."""
        prompt = (
            f"Write a professional email reply.\n"
            f"Original email from: {original.get('from','')}\n"
            f"Subject: {original.get('subject','')}\n"
            f"Body: {original.get('body','')[:500]}\n"
        )
        if instruction:
            prompt += f"\nInstruction: {instruction}"
        try:
            return brain.ask(prompt)
        except Exception as e:
            return f"Could not draft reply: {e}"

    def ai_compose(self, brain, to: str, topic: str) -> dict:
        """Use AI to compose a full email (subject + body) for a given topic/request."""
        prompt = (
            f"Compose a professional email to {to}.\n"
            f"Topic / request: {topic}\n"
            f"Return ONLY:\nSUBJECT: <subject line>\nBODY:\n<body text>"
        )
        try:
            raw = brain.ask(prompt)
            subject, body = "", raw
            if "SUBJECT:" in raw:
                parts = raw.split("BODY:", 1)
                subject = parts[0].replace("SUBJECT:", "").strip()
                body = parts[1].strip() if len(parts) > 1 else raw
            return {"subject": subject, "body": body}
        except Exception as e:
            return {"subject": f"Re: {topic}", "body": f"Error composing: {e}"}
