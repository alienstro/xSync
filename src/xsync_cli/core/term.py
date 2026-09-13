"""The terminal style.

The module writes ANSI codes only for a terminal. It writes plain text
for a pipe, for a dumb terminal, and when the variable NO_COLOR holds a
value. The variable FORCE_COLOR turns the color on again.
"""

from __future__ import annotations

import os
import re
import sys

RESET = "\x1b[0m"
_CODES = {
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _is_set(name: str) -> bool:
    """True when the variable holds a value other than 0, false, or no."""
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() not in ("", "0", "false", "no")


def supports_color() -> bool:
    """True when the output accepts ANSI codes."""
    # The rule of no-color.org: the variable disables the color when it
    # is present and it is not empty. The value 0 also disables it.
    if os.environ.get("NO_COLOR", "") != "":
        return False
    if _is_set("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    stream = sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: str, *names: str) -> str:
    """Add one or more style codes to the text."""
    if not names or not supports_color():
        return text
    prefix = "".join(_CODES[name] for name in names)
    return f"{prefix}{text}{RESET}"


def bold(text: str) -> str:
    return paint(text, "bold")


def dim(text: str) -> str:
    return paint(text, "dim")


def red(text: str) -> str:
    return paint(text, "red")


def green(text: str) -> str:
    return paint(text, "green")


def yellow(text: str) -> str:
    return paint(text, "yellow")


def blue(text: str) -> str:
    return paint(text, "blue")


def cyan(text: str) -> str:
    return paint(text, "cyan")


def width(text: str) -> int:
    """The printed width of the text. The style codes count as nothing."""
    return len(_ANSI.sub("", text))


def pad(text: str, size: int) -> str:
    """Add spaces on the right until the text fills the size."""
    return text + " " * max(0, size - width(text))


def rule(size: int = 64) -> str:
    """A horizontal line."""
    return dim("─" * size)


def heading(title: str) -> str:
    """A title line."""
    return f"\n{bold(cyan(title))}"


def mask_key(key: str | None) -> str:
    """The first five characters of a key, and nothing more.

    The function never shows the length of the key.
    """
    if not key:
        return "(none)"
    if len(key) <= 5:
        return "…"
    return f"{key[:5]}…"
