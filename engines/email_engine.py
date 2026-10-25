import email
import email.header
import imaplib
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

from utils.config import Config


log = logging.getLogger("Flexie.Email")


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
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="ignore")
        except Exception:
            pass
    return body.strip()


def _imap_connect():
    """Return an authenticated IMAP4_SSL connection or raise."""
    if not (Config.EMAIL_ADDRESS and Config.EMAIL_PASSWORD):
        raise RuntimeError("Email credentials not configured (EMAIL_ADDRESS / EMAIL_PASSWORD).")
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(Config.EMAIL_ADDRESS, Config.EMAIL_PASSWORD)
    return m


class EmailEngine:
    def __init__(self):
        self.addr = Config.EMAIL_ADDRESS
        self.pwd  = Config.EMAIL_PASSWORD
        # In-session cache for last-fetched emails so handlers can reference "email 2"
        self._last_inbox: list[dict] = []

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
        """Fetch unread emails from inbox with full metadata."""
        if not self._is_configured():
            return [{"error": "Email credentials not configured."}]
        try:
            m = _imap_connect()
            m.select("INBOX")
            _, ids = m.search(None, "UNSEEN")
            id_list = ids[0].split()
            results = []
            for mid in id_list[-count:]:
                _, data = m.fetch(mid, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                results.append({
                    "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    "from": _decode_header(msg.get("From", "")),
                    "to": _decode_header(msg.get("To", "")),
                    "subject": _decode_header(msg.get("Subject", "(no subject)")),
                    "date": msg.get("Date", ""),
                    "preview": _extract_body(msg)[:300],
                    "body": _extract_body(msg),
                    "read": False,
                })
            m.logout()
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
            m = _imap_connect()
            m.select(folder)
            _, ids = m.search(None, "ALL")
            id_list = ids[0].split()
            results = []
            for mid in id_list[-count:]:
                _, data = m.fetch(mid, "(RFC822 FLAGS)")
                raw_msg = data[0][1]
                flags = data[0][0].decode() if isinstance(data[0][0], bytes) else str(data[0][0])
                msg = email.message_from_bytes(raw_msg)
                results.append({
                    "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    "from": _decode_header(msg.get("From", "")),
                    "to": _decode_header(msg.get("To", "")),
                    "subject": _decode_header(msg.get("Subject", "(no subject)")),
                    "date": msg.get("Date", ""),
                    "preview": _extract_body(msg)[:300],
                    "body": _extract_body(msg),
                    "read": "\\Seen" in flags,
                })
            m.logout()
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
        """Search inbox by subject OR sender keyword."""
        if not self._is_configured():
            return [{"error": "Email credentials not configured."}]
        try:
            m = _imap_connect()
            m.select("INBOX")
            q = query.strip()
            # Try OR between SUBJECT and FROM searches
            _, ids_subj = m.search(None, f'SUBJECT "{q}"')
            _, ids_from = m.search(None, f'FROM "{q}"')
            _, ids_body = m.search(None, f'BODY "{q}"')
            id_set = set(
                ids_subj[0].split() +
                ids_from[0].split() +
                ids_body[0].split()
            )
            results = []
            for mid in list(id_set)[-count:]:
                _, data = m.fetch(mid, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                results.append({
                    "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    "from": _decode_header(msg.get("From", "")),
                    "subject": _decode_header(msg.get("Subject", "(no subject)")),
                    "date": msg.get("Date", ""),
                    "preview": _extract_body(msg)[:200],
                    "body": _extract_body(msg),
                })
            m.logout()
            return results
        except Exception as e:
            log.error("search_emails: %s", e)
            return [{"error": f"Search failed: {e}"}]

    def get_sent_emails(self, count: int = 5) -> list[dict]:
        """Fetch recently sent emails."""
        folders = ["[Gmail]/Sent Mail", "Sent", "Sent Messages"]
        for folder in folders:
            try:
                result = self.get_all_emails(count=count, folder=f'"{folder}"')
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
            m = _imap_connect()
            m.select("INBOX")
            _, unread_ids = m.search(None, "UNSEEN")
            _, all_ids = m.search(None, "ALL")
            unread = len(unread_ids[0].split()) if unread_ids[0] else 0
            total = len(all_ids[0].split()) if all_ids[0] else 0
            m.logout()
            return {"unread": unread, "total": total}
        except Exception as e:
            return {"error": str(e)}

    def get_folders(self) -> list[str]:
        """List all IMAP mailbox folders."""
        if not self._is_configured():
            return []
        try:
            m = _imap_connect()
            _, folders = m.list()
            m.logout()
            names = []
            for f in folders:
                parts = f.decode().split('"/"')
                if parts:
                    names.append(parts[-1].strip().strip('"'))
            return names
        except Exception as e:
            log.error("get_folders: %s", e)
            return []

    # ─────────────────────────────────────────────────────────────────
    # STATUS CHANGES
    # ─────────────────────────────────────────────────────────────────

    def mark_as_read(self, email_id: str) -> str:
        """Mark a specific email as read by IMAP ID."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            m = _imap_connect()
            m.select("INBOX")
            m.store(email_id, "+FLAGS", "\\Seen")
            m.logout()
            return f"Email {email_id} marked as read."
        except Exception as e:
            return f"Failed to mark as read: {e}"

    def mark_as_unread(self, email_id: str) -> str:
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            m = _imap_connect()
            m.select("INBOX")
            m.store(email_id, "-FLAGS", "\\Seen")
            m.logout()
            return f"Email {email_id} marked as unread."
        except Exception as e:
            return f"Failed: {e}"

    def delete_email(self, email_id: str) -> str:
        """Move email to Trash (Gmail) and expunge."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            m = _imap_connect()
            m.select("INBOX")
            # Gmail: move to Trash label
            m.store(email_id, "+FLAGS", "\\Deleted")
            m.copy(email_id, "[Gmail]/Trash")
            m.expunge()
            m.logout()
            return f"Email {email_id} deleted."
        except Exception as e:
            return f"Failed to delete: {e}"

    def archive_email(self, email_id: str) -> str:
        """Move email to Gmail archive ([Gmail]/All Mail) and remove from Inbox."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            m = _imap_connect()
            m.select("INBOX")
            m.copy(email_id, "[Gmail]/All Mail")
            m.store(email_id, "+FLAGS", "\\Deleted")
            m.expunge()
            m.logout()
            return f"Email {email_id} archived."
        except Exception as e:
            return f"Failed to archive: {e}"

    def move_to_folder(self, email_id: str, folder: str) -> str:
        """Move email to the specified IMAP folder."""
        if not self._is_configured():
            return "Email credentials not configured."
        try:
            m = _imap_connect()
            m.select("INBOX")
            m.copy(email_id, folder)
            m.store(email_id, "+FLAGS", "\\Deleted")
            m.expunge()
            m.logout()
            return f"Email moved to {folder}."
        except Exception as e:
            return f"Failed to move: {e}"

    # ─────────────────────────────────────────────────────────────────
    # SEND / COMPOSE / DRAFT
    # ─────────────────────────────────────────────────────────────────

    def send_email(self, to: str, subject: str, body: str) -> str:
        if not self._is_configured():
            return "Email credentials not configured."
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
            m = _imap_connect()
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.addr
            msg["To"] = to
            msg["Date"] = formatdate(localtime=True)
            draft_folder = "[Gmail]/Drafts"
            m.append(draft_folder, "\\Draft", imaplib.Time2Internaldate(None), msg.as_bytes())
            m.logout()
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
        if to:      params["to"] = to
        if subject: params["su"] = subject
        if body:    params["body"] = body[:2000]
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
