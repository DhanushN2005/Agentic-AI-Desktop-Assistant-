"""Unit tests for CLI tool."""
from main import build_parser, process_action


def test_process_action():
    assert process_action("hello") == "hello"
    assert process_action("hello", uppercase=True) == "HELLO"


def test_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.text == "Hello, World!"
    assert args.uppercase is False


def test_parser_custom_args():
    parser = build_parser()
    args = parser.parse_args(["custom text", "-u"])
    assert args.text == "custom text"
    assert args.uppercase is True
