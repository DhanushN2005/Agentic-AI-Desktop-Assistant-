"""Shared test isolation.

Build jobs create a workspace folder (and run ``git init`` in it) under
``Config.CODE_OUTPUT_DIR``, which defaults to the user's Downloads folder. Without this
fixture every test run left new ``full-stack-web-app-<id>`` folders there.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_code_output_dir(tmp_path_factory, monkeypatch):
    from utils.config import Config
    out = tmp_path_factory.mktemp("code_output")
    monkeypatch.setattr(Config, "CODE_OUTPUT_DIR", str(out), raising=False)
    monkeypatch.setenv("FLEXIE_CODE_OUTPUT_DIR", str(out))
