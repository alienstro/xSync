"""The reader of the Codex configuration and of the xSync state file."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from xsync_cli.core.profiles import Profile

STATE_FILENAME = ".xsync-state.json"
STATE_VERSION = 1


class ConfigError(Exception):
    """The Codex configuration cannot be read or written."""


def default_codex_home() -> Path:
    """The Codex home directory."""
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def read_config(path: Path) -> dict[str, Any]:
    """Read `config.toml`. An absent file gives an empty mapping."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from None


def active_provider(config: dict[str, Any]) -> tuple[str, str] | None:
    """The active provider name and its base URL."""
    name = config.get("model_provider")
    if not isinstance(name, str):
        return None
    table = (config.get("model_providers") or {}).get(name)
    if not isinstance(table, dict):
        return None
    return name, str(table.get("base_url", "")).rstrip("/")


def check_provider_match(config: dict[str, Any], profile: Profile) -> str | None:
    """Confirm that Codex routes to the endpoint of the profile.

    The function gives an error message on a mismatch, and None on a
    match.
    """
    current = active_provider(config)
    if current is None:
        return (
            f"Codex has no active model provider.\n"
            f"run: xsync codex --profile {profile.name} --init"
        )
    name, base_url = current
    if base_url != profile.base_url:
        return (
            f'catalog would come from "{profile.name}" ({profile.base_url})\n'
            f'but Codex routes to "{name}" ({base_url})\n'
            f"run: xsync codex --profile {profile.name} --init"
        )
    return None


def wire_api_for_url(config: dict[str, Any], base_url: str) -> str | None:
    """The wire API that Codex already uses for one base URL.

    The function gives None when no provider block holds that URL.
    """
    wanted = base_url.rstrip("/")
    for table in (config.get("model_providers") or {}).values():
        if not isinstance(table, dict):
            continue
        if str(table.get("base_url", "")).rstrip("/") == wanted:
            value = table.get("wire_api")
            return str(value) if value else None
    return None


def catalog_path_for(profile: Profile, codex_home: Path) -> Path:
    """The catalog file of one profile."""
    return codex_home / f"{profile.name}-models.json"


def file_sha256(path: Path) -> str:
    """The hash of a file. An absent file gives an empty string."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class State:
    """The record of what xSync wrote."""

    profile: str
    keys_written: list[str] = field(default_factory=list)
    blocks_written: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    config_sha256: str = ""
    written_at: str = ""


def read_state(path: Path) -> State | None:
    """Read the state file. An absent file gives None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from None
    codex = data.get("codex") or {}
    return State(
        profile=codex.get("profile", ""),
        keys_written=list(codex.get("keys_written", [])),
        blocks_written=list(codex.get("blocks_written", [])),
        files_written=list(codex.get("files_written", [])),
        config_sha256=codex.get("config_sha256", ""),
        written_at=codex.get("written_at", ""),
    )


def write_state(path: Path, state: State) -> None:
    """Write the state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": STATE_VERSION, "codex": asdict(state)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_state(path: Path) -> None:
    """Delete the state file."""
    path.unlink(missing_ok=True)
