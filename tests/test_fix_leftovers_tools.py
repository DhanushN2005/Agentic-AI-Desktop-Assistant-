"""Regression tests for SF-3, TL-15, TL-12, TL-22."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from core.capabilities import CapabilityPolicy
from core.permission_system import PermissionLevel, PermissionSystem
from core.tool_registry import ActionResult, ToolRegistry, ToolSpec

HDR = {"Authorization": "Bearer t0k"}


# ------------------------------------------------------------------ SF-3
def _mail_client(monkeypatch, with_ps=True, wait="3"):
    from fastapi.testclient import TestClient

    from interface.api_server import create_app
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "t0k")
    monkeypatch.setenv("FLEXIE_MAIL_APPROVAL_WAIT", wait)
    orch = MagicMock()
    orch.cmd_queue = MagicMock()
    orch.controller = None
    orch.email.send_email.return_value = "sent"
    orch.email.reply_email.return_value = "replied"
    orch.permission_system = PermissionSystem() if with_ps else None
    return TestClient(create_app(orch)), orch


def test_mail_send_not_sent_without_approval(monkeypatch):
    client, orch = _mail_client(monkeypatch, wait="0.3")
    r = client.post("/api/flexie/mail/send", headers=HDR, json={"to": "a@b.com", "subject": "s", "body": "b"})
    assert r.status_code == 403
    orch.email.send_email.assert_not_called()


def _approve_when_pending(ps, approve=True):
    def run():
        for _ in range(100):
            req = ps.get_pending_request()
            if req:
                (ps.approve_request if approve else ps.reject_request)(req["id"])
                return
            time.sleep(0.03)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_mail_send_and_reply_go_out_only_after_approve(monkeypatch):
    client, orch = _mail_client(monkeypatch)
    t = _approve_when_pending(orch.permission_system)
    r = client.post("/api/flexie/mail/send", headers=HDR, json={"to": "a@b.com", "subject": "s", "body": "b"})
    t.join()
    assert r.status_code == 200 and r.json()["result"] == "sent"
    orch.email.send_email.assert_called_once()
    orch.email._last_inbox = []
    t = _approve_when_pending(orch.permission_system)
    r = client.post("/api/flexie/mail/reply", headers=HDR, json={"to": "a@b.com", "body": "hi"})
    t.join()
    assert r.status_code == 200
    orch.email.reply_email.assert_called_once()


def test_mail_send_rejected_does_not_send(monkeypatch):
    client, orch = _mail_client(monkeypatch)
    t = _approve_when_pending(orch.permission_system, approve=False)
    r = client.post("/api/flexie/mail/send", headers=HDR, json={"to": "a@b.com", "subject": "s", "body": "b"})
    t.join()
    assert r.status_code == 403
    orch.email.send_email.assert_not_called()


def test_mail_send_fails_closed_without_permission_system(monkeypatch):
    client, orch = _mail_client(monkeypatch, with_ps=False)
    r = client.post("/api/flexie/mail/send", headers=HDR, json={"to": "a@b.com", "subject": "s", "body": "b"})
    assert r.status_code == 503
    orch.email.send_email.assert_not_called()


# ------------------------------------------------------------------ TL-15
def _executor_with(tool):
    from core.agent_executor import AgentExecutor
    reg = ToolRegistry()
    reg.register(tool)
    ex = AgentExecutor(reg, PermissionSystem(), orch=MagicMock())
    step = MagicMock()
    step.tool = tool.name
    step.arguments = {}
    return ex, step


@pytest.mark.parametrize("idem,expected", [(None, False), (False, False), (True, True)])
def test_only_explicit_idempotent_true_is_retried(idem, expected):
    tool = ToolSpec(name="t.x", description="d", params=[], permission=PermissionLevel.READ_ONLY,
                    execute_fn=lambda: ActionResult.ok("x", intent="t.x"), idempotent=idem)
    ex, step = _executor_with(tool)
    assert ex._repeatable(step, None) is expected
    assert ex._repeatable(step, ActionResult.fail("boom", intent="t.x")) is expected


def test_registry_repeatable_does_not_infer():
    spec = ToolSpec(name="t.y", description="d", params=[], permission=PermissionLevel.READ_ONLY,
                    execute_fn=lambda: None)
    assert ToolRegistry._repeatable(spec) is False


# ------------------------------------------------------------------ TL-12
def test_test_run_is_safe_action_not_read_only():
    from core.coding_tools import register_coding_tools
    reg = ToolRegistry()
    register_coding_tools(reg, MagicMock())
    spec = reg._tools["test.run"]
    assert spec.permission == PermissionLevel.SAFE_ACTION
    assert "shell:execute" in spec.capabilities


# ------------------------------------------------------------------ TL-22
def test_default_policy_denies_undeclared_capabilities():
    reg = ToolRegistry()
    spec = ToolSpec(name="t.net", description="d", params=[], permission=PermissionLevel.READ_ONLY,
                    execute_fn=lambda: ActionResult.ok("ok", intent="t.net"), tags=["browser"])
    reg.register(spec)
    res = reg.execute("t.net", {})
    assert not res.success and "not declared" in res.message
    # declaring it fixes it
    reg2 = ToolRegistry()
    spec.capabilities = ["network:fetch"]
    reg2.register(spec)
    assert reg2.execute("t.net", {}).success
    # explicit opt-out remains possible
    reg3 = ToolRegistry(policy=CapabilityPolicy(require_declared=False))
    spec.capabilities = []
    reg3.register(spec)
    assert reg3.execute("t.net", {}).success


def test_every_repo_tool_declares_its_capabilities():
    from core.browser_and_comm_tools import register_browser_and_comm_tools
    from core.coding_tools import register_coding_tools
    reg = ToolRegistry()
    register_coding_tools(reg, MagicMock())
    register_browser_and_comm_tools(reg, MagicMock())
    undeclared = [n for n, t in reg._tools.items() if t.effective_capabilities() and not t.capabilities]
    assert undeclared == []
    assert CapabilityPolicy().validate_tool([], ["network:fetch"])[0] is False
