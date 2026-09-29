"""Batch 4 audit fixes: installer mapping, requirements caps, docs drift."""
import pathlib
from unittest.mock import patch

import utils.installer as inst


# --- 12. installer ---
def test_import_names_separate_pip_from_import():
    assert inst._import_name("google-genai") == "google.genai"
    assert inst._import_name("edge-tts") == "edge_tts"
    assert inst._import_name("pymupdf") == "fitz"
    assert inst._import_name("webrtcvad-wheels") == "webrtcvad"
    assert inst._import_name("python-dotenv") == "dotenv"
    assert inst._import_name("SpeechRecognition") == "speech_recognition"


def test_required_packages_complete():
    for pkg in ("vosk", "openai", "anthropic", "langgraph", "chromadb",
                "onnxruntime", "docker", "pymupdf", "pytesseract",
                "webrtcvad-wheels"):
        assert pkg in inst.REQUIRED_PACKAGES, pkg


def test_install_missing_returns_failures():
    with patch.object(inst.importlib.util, "find_spec", return_value=object()):
        assert inst.install_missing() == []
    with patch.object(inst.importlib.util, "find_spec", return_value=None), \
         patch.object(inst.subprocess, "check_call", side_effect=RuntimeError("no net")):
        failed = inst.install_missing()
        assert set(failed) >= set(inst.REQUIRED_PACKAGES)


# --- 13. requirements caps ---
def _req_lines():
    return pathlib.Path("requirements.txt").read_text(encoding="utf-8").splitlines()


def test_upper_bound_pins():
    text = "\n".join(_req_lines())
    for pin in ("playwright>=1.52.0,<2.0.0",
                "google-genai>=1.0.0,<2.0.0",
                "groq>=0.4.0,<1.0.0",
                "openai>=1.30.0,<3.0.0",
                "anthropic>=0.40.0,<1.0.0",
                "websockets>=12.0,<17.0.0",
                "chromadb>=0.4.0,<2.0.0",
                "langgraph>=0.0.299,<2.0.0"):
        assert pin in text, pin


def test_webrtcvad_replaced():
    lines = [l for l in _req_lines() if not l.strip().startswith("#")]
    assert not any(l.startswith("webrtcvad>=") or l.startswith("webrtcvad==") for l in lines)
    assert any(l.startswith("webrtcvad-wheels>=") for l in lines)


def test_major_upgrade_notes_present():
    text = pathlib.Path("requirements.txt").read_text(encoding="utf-8")
    assert "Major-upgrade notes" in text and "chromadb 0.x -> 1.x" in text


# --- 14. docs drift ---
def test_readme_counts_models_ports():
    text = pathlib.Path("README.md").read_text(encoding="utf-8")
    assert "480 test cases across 18 test files" in text
    assert "385" not in text
    assert "1.5-flash" not in text
    assert "2.0-flash" in text
    assert "openai/gpt-oss-20b" in text
    assert "8765" in text and "9886/9887" in text


def test_readme_license_and_agpl_note():
    text = pathlib.Path("README.md").read_text(encoding="utf-8")
    assert "## License" in text and "AGPL" in text


def test_features_ports_and_providers():
    text = pathlib.Path("README_FEATURES.md").read_text(encoding="utf-8")
    assert "10000" not in text
    assert "9886" in text and "8765" in text
    assert "DeepSeek" in text and "Anthropic" in text
