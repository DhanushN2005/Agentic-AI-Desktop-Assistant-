import pytest
from unittest.mock import MagicMock
from core.permission_system import PermissionSystem
from core.tool_registry import PermissionLevel
from core.controller import FlexieController


def test_permission_system_approval_lifecycle():
    ps = PermissionSystem(default_level=PermissionLevel.READ_ONLY)
    received = []
    ps.set_approval_callback(lambda req: received.append(req))

    req = ps.create_approval_request("delete file project.zip", level=PermissionLevel.USER_CONFIRMATION)
    assert req["action"] == "delete file project.zip"
    assert req["status"] == "pending"
    assert len(received) == 1
    assert ps.get_pending_request() == req

    # Approving request should escalate permission
    approved = ps.approve_request(req["id"])
    assert approved is True
    assert ps.current_level == PermissionLevel.USER_CONFIRMATION
    assert ps.get_pending_request() is None


def test_permission_system_reject_lifecycle():
    ps = PermissionSystem(default_level=PermissionLevel.READ_ONLY)
    req = ps.create_approval_request("terminate process 1234", level=PermissionLevel.SENSITIVE)
    assert ps.get_pending_request() is not None

    rejected = ps.reject_request(req["id"])
    assert rejected is True
    assert ps.get_pending_request() is None
    assert ps.current_level == PermissionLevel.READ_ONLY


def test_controller_requires_permission_approval():
    import threading
    mock_orch = MagicMock()
    mock_orch._action_thread_id = threading.get_ident()
    mock_orch.permission_system = PermissionSystem(default_level=PermissionLevel.READ_ONLY)
    mock_orch.spoken = []
    mock_orch.speak = lambda text, **kw: mock_orch.spoken.append(text)
    mock_orch.send_to_ui = MagicMock()

    calls = []
    controller = FlexieController(mock_orch, lambda cmd: calls.append(cmd) or "ok")

    status = controller.execute("delete file document.docx")
    assert status == "awaiting_confirmation"
    assert controller.pending_confirmation == "delete file document.docx"
    assert mock_orch.send_to_ui.called

    # Confirm action
    status_confirm = controller.execute("confirm")
    assert status_confirm == "executed"
    assert "delete file document.docx" in calls
    assert controller.pending_confirmation is None
