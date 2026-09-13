"""The reader and the writer of the Claude Code settings.

Claude Code keeps the rows of the `/model` picker in
`modelPicker.options`. It keeps the endpoint in the `env` block. This
module changes those two keys and nothing else.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from xsync_cli.core.profiles import Profile

STATE_FILENAME = ".xsync-state.json"
STATE_VERSION = 1
BASE_URL_KEY = "ANTHROPIC_BASE_URL"
TOKEN_KEY = "ANTHROPIC_AUTH_TOKEN"
PICKER_KEY = "modelPicker"


class ClaudeConfigError(Exception):
    """The settings file cannot be read or written."""


def default_claude_home() -> Path:
    """The Claude Code home directory."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def settings_path_for(claude_home: Path) -> Path:
    """The settings file of that home."""
    return claude_home / "settings.json"


def file_sha256(path: Path) -> str:
    """The hash of a file. An absent file gives an empty string."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_settings(path: Path) -> dict[str, Any]:
    """Read the settings. An absent file gives an empty mapping."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ClaudeConfigError(f"{path} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ClaudeConfigError(f"{path} does not hold a JSON object.")
    return data


def base_url_of(settings: dict[str, Any]) -> str | None:
    """The endpoint that Claude Code uses."""
    value = (settings.get("env") or {}).get(BASE_URL_KEY)
    return str(value).rstrip("/") if value else None


def check_endpoint_match(settings: dict[str, Any], profile: Profile) -> str | None:
    """Confirm that Claude Code talks to the endpoint of the profile."""
    current = base_url_of(settings)
    if current is None:
        return (
            "Claude Code has no endpoint.\n"
            f"run: xsync claude --profile {profile.name} --init"
        )
    if current != profile.base_url:
        return (
            f'the rows would come from "{profile.name}" ({profile.base_url})\n'
            f"but Claude Code talks to {current}\n"
            f"run: xsync claude --profile {profile.name} --init"
        )
    return None


@dataclass(frozen=True, slots=True)
class State:
    """The record of what xSync wrote into the settings."""

    profile: str
    keys_written: list[str] = field(default_factory=list)
    settings_sha256: str = ""
    written_at: str = ""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_atomic(path: Path, data: dict[str, Any], before: str) -> None:
    """Write the settings only when the file did not change."""
    if file_sha256(path) != before:
        raise ClaudeConfigError(
            f"{path} changed during the edit. Close Claude Code and try again."
        )
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    json.loads(text)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    if path.exists():
        path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
    os.replace(temporary, path)


def init_settings(path: Path, profile: Profile, api_key: str | None) -> State:
    """Point Claude Code at the endpoint of the profile."""
    before = file_sha256(path)
    settings = read_settings(path)

    environment = dict(settings.get("env") or {})
    environment[BASE_URL_KEY] = profile.base_url
    keys = [f"env.{BASE_URL_KEY}"]
    if api_key:
        environment[TOKEN_KEY] = api_key
        keys.append(f"env.{TOKEN_KEY}")
    settings["env"] = environment

    _write_atomic(path, settings, before)
    return State(
        profile=profile.name,
        keys_written=keys,
        settings_sha256=file_sha256(path),
        written_at=_now(),
    )


def write_picker(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write the rows of the `/model` picker.

    The value `replaceBuiltInOptions` stays false. The built-in models
    stay in the picker, and the rows come after them. A router that
    stops therefore leaves a working picker.
    """
    before = file_sha256(path)
    settings = read_settings(path)
    settings[PICKER_KEY] = {"options": rows, "replaceBuiltInOptions": False}
    _write_atomic(path, settings, before)


def current_rows(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows that the settings hold now."""
    picker = settings.get(PICKER_KEY) or {}
    rows = picker.get("options")
    return list(rows) if isinstance(rows, list) else []


def reset_settings(path: Path, state: State) -> list[str]:
    """Remove every key that the state records."""
    before = file_sha256(path)
    settings = read_settings(path)
    removed: list[str] = []

    for key in state.keys_written:
        parent, _, child = key.partition(".")
        if child:
            table = settings.get(parent)
            if isinstance(table, dict) and child in table:
                del table[child]
                removed.append(key)
                if not table:
                    del settings[parent]
        elif parent in settings:
            del settings[parent]
            removed.append(parent)

    _write_atomic(path, settings, before)
    return removed


def read_state(path: Path) -> State | None:
    """Read the state file. An absent file gives None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ClaudeConfigError(f"{path} is not valid JSON: {error}") from None
    entry = data.get("claude") or {}
    return State(
        profile=entry.get("profile", ""),
        keys_written=list(entry.get("keys_written", [])),
        settings_sha256=entry.get("settings_sha256", ""),
        written_at=entry.get("written_at", ""),
    )


def write_state(path: Path, state: State) -> None:
    """Write the state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": STATE_VERSION, "claude": asdict(state)}, indent=2),
        encoding="utf-8",
    )


def clear_state(path: Path) -> None:
    """Delete the state file."""
    path.unlink(missing_ok=True)
