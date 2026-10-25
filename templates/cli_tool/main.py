"""Command Line Interface Utility."""
from __future__ import annotations

import argparse
import sys


def process_action(text: str, uppercase: bool = False) -> str:
    """Format input text according to options."""
    if uppercase:
        return text.upper()
    return text.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flexie CLI Utility")
    parser.add_argument("text", nargs="?", default="Hello, World!", help="Text to process")
    parser.add_argument("-u", "--uppercase", action="store_true", help="Convert text to uppercase")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    output = process_action(args.text, uppercase=args.uppercase)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
