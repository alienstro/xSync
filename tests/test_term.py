import io

import pytest

from xsync_cli.core import term


@pytest.fixture(autouse=True)
def plain_env(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


def as_tty(monkeypatch, value: bool):
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: value, raising=False)
    monkeypatch.setattr(term.sys, "stdout", stream)


def test_color_is_on_for_a_terminal(monkeypatch):
    as_tty(monkeypatch, True)
    assert term.supports_color() is True


def test_color_is_off_for_a_pipe(monkeypatch):
    as_tty(monkeypatch, False)
    assert term.supports_color() is False


def test_no_color_turns_the_color_off(monkeypatch):
    as_tty(monkeypatch, True)
    monkeypatch.setenv("NO_COLOR", "1")
    assert term.supports_color() is False


def test_a_dumb_terminal_gets_no_color(monkeypatch):
    as_tty(monkeypatch, True)
    monkeypatch.setenv("TERM", "dumb")
    assert term.supports_color() is False


def test_style_adds_a_code_for_a_terminal(monkeypatch):
    as_tty(monkeypatch, True)
    assert term.green("ok") == "\x1b[32mok\x1b[0m"


def test_style_adds_nothing_for_a_pipe(monkeypatch):
    as_tty(monkeypatch, False)
    assert term.green("ok") == "ok"


def test_every_style_keeps_the_text(monkeypatch):
    as_tty(monkeypatch, False)
    for style in (term.bold, term.dim, term.green, term.red, term.yellow, term.cyan):
        assert style("text") == "text"


def test_the_width_of_a_styled_string_ignores_the_codes(monkeypatch):
    as_tty(monkeypatch, True)
    assert term.width(term.green("abc")) == 3


def test_mask_key_keeps_the_first_five_characters():
    assert term.mask_key("sk-92465eb0c2f2e2d5") == "sk-92…"


def test_mask_key_of_a_short_key_shows_no_character():
    assert term.mask_key("abc") == "…"


def test_mask_key_of_no_key_says_none():
    assert term.mask_key(None) == "(none)"
    assert term.mask_key("") == "(none)"


def test_rule_fills_the_width(monkeypatch):
    as_tty(monkeypatch, False)
    assert term.rule(10) == "─" * 10


def test_a_heading_holds_the_title(monkeypatch):
    as_tty(monkeypatch, False)
    assert "Profiles" in term.heading("Profiles")


def test_force_color_zero_does_not_turn_the_color_on(monkeypatch):
    as_tty(monkeypatch, False)
    monkeypatch.setenv("FORCE_COLOR", "0")
    assert term.supports_color() is False


def test_no_color_zero_still_turns_the_color_off(monkeypatch):
    as_tty(monkeypatch, True)
    monkeypatch.setenv("NO_COLOR", "0")
    assert term.supports_color() is False
