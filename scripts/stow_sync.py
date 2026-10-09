#!/usr/bin/env python3
"""Stow Sync backend helper.

Every invocation prints exactly one JSON object to stdout:

    {"ok": true, ...} or {"ok": false, "error": "<short human text>"}

The command set grows in later units; Unit 0 only answers ``version``.
``main()`` wraps everything so a failure never leaks a traceback to the panel.
"""

from __future__ import annotations

import json
import sys
from typing import Any

VERSION = "0.1.0"


def cmd_version(_argv: list[str]) -> dict[str, Any]:
    """Report the backend version."""
    return {"ok": True, "version": VERSION}


COMMANDS = {
    "version": cmd_version,
}


def dispatch(argv: list[str]) -> dict[str, Any]:
    """Route one already-parsed argument vector to its command handler."""
    name = argv[0] if argv else ""
    handler = COMMANDS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown command: " + (name or "<none>")}
    return handler(argv[1:])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = dispatch(args)
    except Exception as exc:  # noqa: BLE001 - CLI must never print a traceback to QML
        result = {"ok": False, "error": (str(exc) or exc.__class__.__name__)}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
