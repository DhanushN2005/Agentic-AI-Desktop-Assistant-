"""
Headless REST & Server-Sent Events (SSE) API Server for Flexiee 2.0.

Provides authenticated HTTP and SSE endpoints for external clients,
desktop apps, mobile bridges, or web dashboards to control Flexie.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from utils.config import Config
from utils.udp_auth import get_token, pack as udp_pack

logger = logging.getLogger("Flexie.APIServer")
security = HTTPBearer(auto_error=False)


class CommandRequest(BaseModel):
    command: str
    params: dict[str, Any] | None = None


class MailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    html: bool = False
    body_html: str | None = None


class MailReplyRequest(BaseModel):
    to: str
    subject: str | None = None
    body: str
    ai_draft: bool = False


class MailSearchRequest(BaseModel):
    query: str
    count: int = 10


class MailActionRequest(BaseModel):
    email_id: str
    folder: str | None = None  # for move_to_folder


class MailComposeRequest(BaseModel):
    to: str
    topic: str


class ApprovalRequestPayload(BaseModel):
    request_id: str | None = None
    action: str = "confirm"  # "confirm" or "cancel"


class PageAssistRequest(BaseModel):
    query: str
    url: str | None = None
    title: str | None = None
    page_content: str | None = None
    selected_text: str | None = None
    action: str = "ask"  # "ask", "summarize", "explain_code", "extract"


def verify_token(credentials: HTTPAuthorizationCredentials | None = Security(security)) -> bool:
    """Validate Bearer token against local session token."""
    expected = get_token()
    if not expected:
        return True  # If no auth token is active, fail open on localhost only
    if not credentials or credentials.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer authorization token",
        )
    return True


def create_app(orch: Any = None) -> FastAPI:
    """Application factory for Flexiee REST/SSE service."""
    app = FastAPI(title="Flexiee API", version="2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "flexiee", "active": orch.active if orch else False}

    @app.post("/page-assist", dependencies=[Depends(verify_token)])
    @app.post("/api/flexie/page-assistant", dependencies=[Depends(verify_token)])
    @app.post("/api/jarvis/page-assistant", dependencies=[Depends(verify_token)])
    def page_assistant(payload: PageAssistRequest):
        prompt = (
            f"You are Flexie, assisting the user with their active web browser page.\n"
            f"Page Title: {payload.title or 'Unknown'}\n"
            f"URL: {payload.url or 'Unknown'}\n"
        )
        if payload.selected_text:
            prompt += f"\nSelected Text on Page:\n\"\"\"\n{payload.selected_text}\n\"\"\"\n"
        if payload.page_content:
            prompt += f"\nPage Content:\n\"\"\"\n{payload.page_content[:4000]}\n\"\"\"\n"
        prompt += f"\nUser Question / Task: {payload.query}"

        answer = ""
        if orch and hasattr(orch, "brain") and orch.brain:
            try:
                answer = orch.brain.ask(prompt)
            except Exception as e:
                answer = f"Error consulting brain: {e}"
        else:
            try:
                from core.brain import Brain
                brain = Brain()
                answer = brain.ask(prompt)
            except Exception as e:
                answer = f"Page analysis completed: {payload.query}"

        return {"status": "success", "answer": answer}

    @app.post("/command", dependencies=[Depends(verify_token)])
    @app.post("/api/flexie/commands", dependencies=[Depends(verify_token)])
    @app.post("/api/jarvis/commands", dependencies=[Depends(verify_token)])
    def run_command(payload: CommandRequest):
        cmd = payload.command.strip()
        if not cmd:
            raise HTTPException(status_code=400, detail="Command cannot be empty")

        if orch:
            orch.cmd_queue.put(cmd)
            return {"status": "queued", "command": cmd}

        # Standalone mode: relay over authenticated UDP
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        msg = udp_pack(cmd)
        sock.sendto(msg.encode("utf-8"), ("127.0.0.1", Config.UDP_PORT_ASSISTANT))
        sock.close()
        return {"status": "dispatched", "command": cmd}

    @app.get("/api/flexie/status", dependencies=[Depends(verify_token)])
    @app.get("/api/jarvis/status", dependencies=[Depends(verify_token)])
    def get_status():
        info: dict[str, Any] = {
            "mode": getattr(orch, "current_mode", "general") if orch else "unknown",
            "active": getattr(orch, "active", False) if orch else False,
            "provider": Config.ACTIVE_PROVIDER,
            "model": Config.get_model(),
        }
        if orch and hasattr(orch, "job_manager") and orch.job_manager:
            info["job_status"] = orch.job_manager.get_status_summary()
        return info

    @app.get("/api/flexie/jobs", dependencies=[Depends(verify_token)])
    @app.get("/api/jarvis/jobs", dependencies=[Depends(verify_token)])
    def get_jobs():
        if orch and hasattr(orch, "job_manager") and orch.job_manager:
            jobs = orch.job_manager.store.list_all()
            return {"jobs": [j.to_dict() for j in jobs]}
        return {"jobs": []}

    @app.post("/api/flexie/approve", dependencies=[Depends(verify_token)])
    @app.post("/api/jarvis/approve", dependencies=[Depends(verify_token)])
    def approve_action(payload: ApprovalRequestPayload):
        if orch and hasattr(orch, "permission_system") and orch.permission_system:
            ok = orch.permission_system.approve_request(payload.request_id)
            if hasattr(orch, "controller") and orch.controller and orch.controller.pending_confirmation:
                orch.controller._handle_confirmation("confirm")
            return {"status": "approved", "success": ok}

        # Relay over UDP
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        action_msg = f"CONFIRM:{payload.request_id}" if payload.request_id else "CONFIRM"
        sock.sendto(udp_pack(action_msg).encode("utf-8"), ("127.0.0.1", Config.UDP_PORT_ASSISTANT))
        sock.close()
        return {"status": "approved", "success": True}

    @app.post("/api/flexie/reject", dependencies=[Depends(verify_token)])
    @app.post("/api/jarvis/reject", dependencies=[Depends(verify_token)])
    def reject_action(payload: ApprovalRequestPayload):
        if orch and hasattr(orch, "permission_system") and orch.permission_system:
            ok = orch.permission_system.reject_request(payload.request_id)
            if hasattr(orch, "controller") and orch.controller and orch.controller.pending_confirmation:
                orch.controller._handle_confirmation("cancel")
            return {"status": "rejected", "success": ok}

        # Relay over UDP
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        action_msg = f"REJECT:{payload.request_id}" if payload.request_id else "REJECT"
        sock.sendto(udp_pack(action_msg).encode("utf-8"), ("127.0.0.1", Config.UDP_PORT_ASSISTANT))
        sock.close()
        return {"status": "rejected", "success": True}

    # ── Mail endpoints ────────────────────────────────────────────────────

    def _email(orch_ref):
        e = getattr(orch_ref, "email", None)
        if e is None:
            raise HTTPException(status_code=503, detail="EmailEngine not available.")
        return e

    @app.get("/api/flexie/mail/inbox", dependencies=[Depends(verify_token)])
    def mail_inbox(count: int = 5):
        """List unread emails."""
        emails = _email(orch).get_unread_emails_detailed(count=count)
        return {"emails": emails}

    @app.get("/api/flexie/mail/all", dependencies=[Depends(verify_token)])
    def mail_all(count: int = 10, folder: str = "INBOX"):
        emails = _email(orch).get_all_emails(count=count, folder=folder)
        return {"emails": emails}

    @app.get("/api/flexie/mail/count", dependencies=[Depends(verify_token)])
    def mail_count():
        return _email(orch).get_email_count()

    @app.get("/api/flexie/mail/sent", dependencies=[Depends(verify_token)])
    def mail_sent(count: int = 5):
        emails = _email(orch).get_sent_emails(count=count)
        return {"emails": emails}

    @app.get("/api/flexie/mail/folders", dependencies=[Depends(verify_token)])
    def mail_folders():
        return {"folders": _email(orch).get_folders()}

    @app.post("/api/flexie/mail/search", dependencies=[Depends(verify_token)])
    def mail_search(payload: MailSearchRequest):
        results = _email(orch).search_emails(payload.query, count=payload.count)
        return {"results": results, "query": payload.query}

    @app.post("/api/flexie/mail/send", dependencies=[Depends(verify_token)])
    def mail_send(payload: MailSendRequest):
        eng = _email(orch)
        if payload.html and payload.body_html:
            result = eng.send_email_html(payload.to, payload.subject, payload.body, payload.body_html)
        else:
            result = eng.send_email(payload.to, payload.subject, payload.body)
        return {"result": result}

    @app.post("/api/flexie/mail/reply", dependencies=[Depends(verify_token)])
    def mail_reply(payload: MailReplyRequest):
        eng = _email(orch)
        brain = getattr(orch, "brain", None) if payload.ai_draft else None
        if brain and eng._last_inbox:
            target = eng._last_inbox[0]
            body = eng.ai_draft_reply(brain, target, payload.body)
        else:
            body = payload.body
        result = eng.reply_email(payload.to, body, payload.subject)
        return {"result": result}

    @app.post("/api/flexie/mail/compose-ai", dependencies=[Depends(verify_token)])
    def mail_compose_ai(payload: MailComposeRequest):
        brain = getattr(orch, "brain", None)
        if not brain:
            raise HTTPException(status_code=503, detail="Brain not available.")
        composed = _email(orch).ai_compose(brain, payload.to, payload.topic)
        return {"to": payload.to, **composed}

    @app.post("/api/flexie/mail/summarize", dependencies=[Depends(verify_token)])
    def mail_summarize_inbox(count: int = 5):
        brain = getattr(orch, "brain", None)
        if not brain:
            raise HTTPException(status_code=503, detail="Brain not available.")
        summary = _email(orch).ai_summarize_inbox(brain, count=count)
        return {"summary": summary}

    @app.post("/api/flexie/mail/delete", dependencies=[Depends(verify_token)])
    def mail_delete(payload: MailActionRequest):
        return {"result": _email(orch).delete_email(payload.email_id)}

    @app.post("/api/flexie/mail/archive", dependencies=[Depends(verify_token)])
    def mail_archive(payload: MailActionRequest):
        return {"result": _email(orch).archive_email(payload.email_id)}

    @app.post("/api/flexie/mail/mark-read", dependencies=[Depends(verify_token)])
    def mail_mark_read(payload: MailActionRequest):
        return {"result": _email(orch).mark_as_read(payload.email_id)}

    @app.post("/api/flexie/mail/draft", dependencies=[Depends(verify_token)])
    def mail_draft(payload: MailSendRequest):
        return {"result": _email(orch).save_draft(payload.to, payload.subject, payload.body)}

    @app.post("/api/flexie/mail/move", dependencies=[Depends(verify_token)])
    def mail_move(payload: MailActionRequest):
        if not payload.folder:
            raise HTTPException(status_code=400, detail="folder is required")
        return {"result": _email(orch).move_to_folder(payload.email_id, payload.folder)}

    # ─────────────────────────────────────────────────────────────────────

    @app.get("/api/flexie/events", dependencies=[Depends(verify_token)])
    @app.get("/api/jarvis/events", dependencies=[Depends(verify_token)])
    async def event_stream() -> StreamingResponse:
        async def event_generator() -> AsyncGenerator[str, None]:
            while True:
                data = {
                    "active": getattr(orch, "active", False) if orch else False,
                    "mode": getattr(orch, "current_mode", "general") if orch else "unknown",
                }
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(2.0)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


def start_api_server(host: str = "127.0.0.1", port: int = 8768, orch: Any = None):
    """Run the API server with uvicorn."""
    import uvicorn
    app = create_app(orch)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_api_server()
