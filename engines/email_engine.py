import email
import imaplib
import smtplib
from email.mime.text import MIMEText

from utils.config import Config
import logging


class EmailEngine:
    def __init__(self):
        self.addr = Config.EMAIL_ADDRESS
        self.pwd  = Config.EMAIL_PASSWORD

    def _is_configured(self) -> bool:
        return bool(self.addr and self.pwd)

    def send_email(self, to: str, subject: str, body: str) -> str:
        if not self._is_configured():
            return "Email is not configured in your settings. Please set your credentials."
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.addr
            msg["To"] = to
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
                srv.login(self.addr, self.pwd)
                srv.send_message(msg)
            return f"Successfully sent email to {to}."
        except Exception as e:
            logging.debug("[engines/email_engine.py:29] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"Failed to send email: {e}"

    def get_unread_emails(self, count: int = 3) -> list[str]:
        detailed = self.get_unread_emails_detailed(count=count)
        if not detailed:
            return ["You have no unread emails."]
        if "error" in detailed[0]:
            return [detailed[0]["error"]]
        return [f"Email from {e['from']}: {e['subject']}" for e in detailed]

    def get_unread_emails_detailed(self, count: int = 5) -> list[dict]:
        """Fetch unread emails with full metadata for AI replies and summaries."""
        if not self._is_configured():
            return [{"error": "Email credentials are missing in configuration."}]
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com")
            m.login(self.addr, self.pwd)
            m.select("inbox")
            _, ids = m.search(None, "UNSEEN")
            msgs = []
            id_list = ids[0].split()
            for mid in id_list[-count:]:
                _, data = m.fetch(mid, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                subject = msg.get("Subject", "No Subject")
                sender = msg.get("From", "Unknown Sender")
                date_str = msg.get("Date", "")
                
                # Extract plain text body preview
                body_preview = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body_preview = part.get_payload(decode=True).decode("utf-8", errors="ignore")[:300]
                                break
                            except Exception:
                                pass
                else:
                    try:
                        body_preview = msg.get_payload(decode=True).decode("utf-8", errors="ignore")[:300]
                    except Exception:
                        pass

                msgs.append({
                    "id": mid.decode("utf-8", errors="ignore") if isinstance(mid, bytes) else str(mid),
                    "from": sender,
                    "subject": subject,
                    "date": date_str,
                    "preview": body_preview.strip(),
                })
            m.logout()
            return msgs
        except Exception as e:
            logging.debug("[engines/email_engine.py] Error reading detailed inbox: %s", e)
            return [{"error": f"Could not read inbox: {e}"}]

    def reply_email(self, to: str, body: str, subject: str | None = None) -> str:
        """Reply to an email address with proper Re: subject line."""
        if not subject:
            subject = "Re: Your message"
        elif not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        if not self._is_configured():
            # Return webmail fallback compose link
            url = self.get_webmail_compose_url(to=to, subject=subject, body=body)
            import webbrowser
            try:
                webbrowser.open(url)
                return f"Credentials not configured. Opened Gmail webmail to send reply to {to}."
            except Exception:
                return f"Email credentials not configured. You can send manually to {to}."

        return self.send_email(to=to, subject=subject, body=body)

    @staticmethod
    def get_webmail_compose_url(to: str = "", subject: str = "", body: str = "") -> str:
        """Construct a Gmail web composer URL for browser automation fallback."""
        import urllib.parse
        params = {"view": "cm", "fs": "1"}
        if to: params["to"] = to
        if subject: params["su"] = subject
        if body: params["body"] = body
        return f"https://mail.google.com/mail/?{urllib.parse.urlencode(params)}"
