import queue
import threading
import types

from core.action_result import ActionResult
from core.workflow_executor import WorkflowExecutor


class FakeLogger:
    def info(self, *args):
        pass

    def warning(self, *args):
        pass

    def error(self, *args):
        pass


class FakeCtx:
    def __init__(self):
        self.last_path = None
        self.active_document = None
        self.last_response = None


class FakeValidator:
    def is_app_running(self, app, window):
        return True


class FakeCapabilityValidator:
    def validate(self, *a, **k):
        return True


class FakeCriticReport:
    quality_score = 100.0

    def __str__(self):
        return "critique report"


class FakeOrch:
    ACTION_TIMEOUTS = {"app_op": 1, "default": 1}

    def __init__(self):
        self.logger = FakeLogger()
        self.ctx = FakeCtx()
        self.validator = FakeValidator()
        self.capability_validator = FakeCapabilityValidator()
        self.router = types.SimpleNamespace(route=lambda c: ("app_op", 1.0))
        self.brain = types.SimpleNamespace()
        self.browser = types.SimpleNamespace(page=None)
        self.files = types.SimpleNamespace()
        self.cmd_queue = queue.Queue()
        self.last_command_time = 0.0
        self.spoken = []
        self.executed = []
        self.recorded = []
        self.dag_calls = []
        self.arbitrator = types.SimpleNamespace(
            acquire_lock=lambda *a, **k: True,
            release_lock=lambda *a, **k: None,
        )
        self.dag_planner = types.SimpleNamespace(execute_graph=lambda tasks: self.dag_calls.append(tasks))
        self.semantic_validator = types.SimpleNamespace(validate_outcome=lambda *a, **k: {"valid": True})
        self.task_critic = types.SimpleNamespace(critique=lambda *a, **k: FakeCriticReport())
        self.execution_graph = types.SimpleNamespace(add_node=lambda *a, **k: None)
        self.adaptive_router = types.SimpleNamespace(record_route=lambda cmd, intent, ok: self.recorded.append((cmd, intent, ok)))

    def speak(self, text, silent=False):
        self.spoken.append(text)

    def handle_command(self, cmd, is_subcommand=False, silent=False, source="user", depth=0):
        self.executed.append(cmd)

    def _normalize_dag_command(self, cmd):
        return cmd


def make_executor():
    return WorkflowExecutor(FakeOrch())


def test_blocking_execute_success():
    orch = FakeOrch()
    executor = WorkflowExecutor(orch)

    def consumer():
        item = orch.cmd_queue.get(timeout=2)
        item[2].append(ActionResult.ok(message="done", intent="app_op"))
        item[1].set()

    t = threading.Thread(target=consumer)
    t.start()
    result = executor.blocking_execute("open notepad", timeout=5)
    t.join()
    assert result.success
    assert result.message == "done"


def test_blocking_execute_timeout(monkeypatch):
    monkeypatch.setattr("core.workflow_executor.threading.Event", lambda: types.SimpleNamespace(wait=lambda timeout: False))
    executor = make_executor()
    result = executor.blocking_execute("open notepad", timeout=1)
    assert not result.success
    assert "Timeout" in result.message


def test_verify_step_folder_exists(tmp_path):
    orch = FakeOrch()
    orch.ctx.last_path = str(tmp_path)
    verified, retries = WorkflowExecutor(orch).verify_step("create a folder projects", {}, "file_op")
    assert verified is True
    assert retries == 0


def test_verify_step_app_running():
    orch = FakeOrch()
    verified, retries = WorkflowExecutor(orch).verify_step("open notepad", {}, "app_op")
    assert verified is True
    assert retries == 0


def test_log_step_result_no_crash():
    executor = make_executor()
    executor.log_step_result("abc12345", 1, 2, "app_op", 0.5, True, 0)


def test_execute_sequential_falls_back_when_dag_fails(monkeypatch):
    monkeypatch.setattr("core.workflow_executor.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("core.workflow_executor.SystemCtrl.get_active_window_title", lambda: "notepad")
    monkeypatch.setattr("core.workflow_executor.SystemCtrl.get_clipboard", lambda: "clip")
    orch = FakeOrch()

    def boom(tasks):
        raise RuntimeError("DAG unavailable")

    orch.dag_planner.execute_graph = boom
    executor = WorkflowExecutor(orch)
    executor.execute(["open notepad"])

    assert orch.executed == ["open notepad"]
    assert orch.recorded == [("open notepad", "app_op", True)]
    assert any("Step 1: open notepad" in s for s in orch.spoken)


def test_execute_uses_dag_for_small_plans(monkeypatch):
    monkeypatch.setattr("core.workflow_executor.time.sleep", lambda *a, **k: None)
    orch = FakeOrch()
    executor = WorkflowExecutor(orch)
    executor.execute(["open notepad"])
    assert orch.dag_calls  # DAG path executed and returned early
    assert orch.executed == []
