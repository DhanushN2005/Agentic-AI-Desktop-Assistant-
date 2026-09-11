import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from typing import List
from utils.config import Config

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
            return f"Failed to send email: {e}"

    def get_unread_emails(self, count: int = 3) -> List[str]:
        if not self._is_configured():
            return ["Email credentials are missing."]
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
                sender  = msg.get("From", "Unknown Sender")
                msgs.append(f"Email from {sender}: {subject}")
            m.logout()
            return msgs if msgs else ["You have no unread emails."]
        except Exception as e:
            return [f"Could not read inbox: {e}"]
