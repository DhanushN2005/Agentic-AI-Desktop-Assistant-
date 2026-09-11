import subprocess

import pytest

from sandbox.executor import SandboxExecutor


class FakeContainer:
    def __init__(self, status="exited", logs=b"container output", exit_code=0):
        self.status = status
        self._logs = logs
        self._exit_code = exit_code

    def reload(self):
        self.status = "exited"

    def logs(self):
        return self._logs

    def wait(self):
        return {"StatusCode": self._exit_code}

    def kill(self):
        self.status = "dead"

    def remove(self):
        pass


class FakeContainers:
    def __init__(self, container=None):
        self.container = container

    def run(self, **kwargs):
        if self.container and isinstance(self.container, Exception):
            raise self.container
        return self.container


class FakeDocker:
    def __init__(self, container=None):
        self.containers = FakeContainers(container)


@pytest.fixture
def executor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ex = SandboxExecutor()
    ex.docker_client = None
    return ex


def write_script(tmp_path, name="script.py", body="print('hello-test')"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_missing_script_refused(executor, monkeypatch):
    def fail_run(*args, **kwargs):
        pytest.fail("host subprocess must not run for a missing script")

    monkeypatch.setattr(subprocess, "run", fail_run)
    result = executor.run_python_script(str(executor.__class__) + "nonexistent.py")
    assert "does not exist" in result


def test_no_docker_refuses_host_execution(executor, monkeypatch, tmp_path):
    """With docker unavailable and fallback disabled, we must NOT run on host."""
    script = write_script(tmp_path)

    def fail_run(*args, **kwargs):
        pytest.fail("host subprocess executed despite sandbox refusal!")

    monkeypatch.setattr(subprocess, "run", fail_run)
    result = executor.run_python_script(script)

    assert "refused" in result
    assert "Sandbox" in result


def test_host_fallback_runs_when_explicitly_enabled(executor, tmp_path):
    executor.allow_host_fallback = True
    script = write_script(tmp_path)
    result = executor.run_python_script(script)
    assert "hello-test" in result


def test_run_python_code_host_fallback(executor, tmp_path):
    executor.allow_host_fallback = True
    result = executor.run_python_code("print(42)")
    assert "42" in result


def test_docker_path_returns_container_logs(executor, tmp_path):
    executor.docker_client = FakeDocker(FakeContainer(logs=b"docker-out\n"))
    script = write_script(tmp_path)
    result = executor.run_python_script(script)
    assert "docker-out" in result


def test_docker_failure_refuses_without_fallback(executor, tmp_path, monkeypatch):
    executor.docker_client = FakeDocker(RuntimeError("docker daemon down"))

    def fail_run(*args, **kwargs):
        pytest.fail("host subprocess executed after docker failure!")

    monkeypatch.setattr(subprocess, "run", fail_run)
    script = write_script(tmp_path)
    result = executor.run_python_script(script)
    assert "refused" in result
