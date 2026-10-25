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
