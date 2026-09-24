"""The writer of the Codex configuration.

Only `--init` and `--reset` use this module. The everyday sync does not
touch `config.toml`.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

import tomlkit

from xsync_cli.adapters.codex_config import ConfigError, State, file_sha256
from xsync_cli.core.profiles import Profile

MANAGED_KEYS = ("model_catalog_json", "model_provider", "model")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(value: Any) -> Any:
    """A tomlkit item as a plain Python value, for the JSON state file."""
    return value.unwrap() if hasattr(value, "unwrap") else value


def _atomic_toml_write(path: Path, document: tomlkit.TOMLDocument, before: str) -> None:
    """Write the document only when the file did not change."""
    if file_sha256(path) != before:
        raise ConfigError(
            f"{path} changed during the edit. Close Codex and try again."
        )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
    os.replace(temporary, path)


def _load_document(path: Path) -> tomlkit.TOMLDocument:
    if not path.exists():
        return tomlkit.document()
    return tomlkit.parse(path.read_text(encoding="utf-8"))


def provider_entry(profile: Profile, api_key: str | None) -> tomlkit.items.Table:
    """Build one Codex provider block."""
    entry = tomlkit.table()
    entry["name"] = "OpenAI" if profile.endpoint_type == "cliproxy" else profile.name
    entry["base_url"] = profile.base_url
    entry["wire_api"] = profile.wire_api

    if profile.endpoint_type == "cliproxy":
        entry["requires_openai_auth"] = True
        if api_key:
            entry["experimental_bearer_token"] = api_key
    elif api_key:
        headers = tomlkit.table()
        headers["Authorization"] = f"Bearer {api_key}"
        entry["http_headers"] = headers
    return entry


def known_removals(profile_name: str) -> State:
    """The removal set when no state file exists."""
    return State(
        profile=profile_name,
        keys_written=list(MANAGED_KEYS),
        blocks_written=[f"model_providers.{profile_name}"],
        files_written=[],
        config_sha256="",
        written_at="",
    )


def init_config(
    config_path: Path,
    profile: Profile,
    catalog_path: Path,
    api_key: str | None,
) -> State:
    """Connect Codex to the endpoint of the profile.

    The function records every key and block that it writes. It also
    records the old value of a key that it replaces, so that a reset can
    put the old value back.
    """
    before = file_sha256(config_path)
    document = _load_document(config_path)

    keys_written: list[str] = []
    keys_replaced: dict[str, Any] = {}
    wanted = {
        "model_catalog_json": str(catalog_path),
        "model_provider": profile.name,
    }
    for key, value in wanted.items():
        old = document.get(key)
        if old is not None and old != value:
            keys_replaced[key] = _plain(old)
        document[key] = value
        keys_written.append(key)

    providers = document.get("model_providers")
    if providers is None:
        providers = tomlkit.table(is_super_table=True)
        document["model_providers"] = providers

    providers[profile.name] = provider_entry(profile, api_key)

    _atomic_toml_write(config_path, document, before)

    return State(
        profile=profile.name,
        keys_written=keys_written,
        blocks_written=[f"model_providers.{profile.name}"],
        files_written=[str(catalog_path)],
        keys_replaced=keys_replaced,
        config_sha256=file_sha256(config_path),
        written_at=_now(),
    )


def reset_config(config_path: Path, state: State) -> list[str]:
    """Remove every item that the state file records.

    The function keeps the backup file `<name>.bak`. The backup is the
    only way back after a reset.
    """
    before = file_sha256(config_path)
    document = _load_document(config_path)
    removed: list[str] = []

    for key in state.keys_written:
        if key in state.keys_replaced:
            document[key] = state.keys_replaced[key]
            removed.append(key)
        elif key in document:
            del document[key]
            removed.append(key)

    for block in state.blocks_written:
        parent_name, _, child = block.partition(".")
        parent = document.get(parent_name)
        if isinstance(parent, dict) and child in parent:
            del parent[child]
            removed.append(block)
            if not parent:
                del document[parent_name]

    _atomic_toml_write(config_path, document, before)

    for name in state.files_written:
        path = Path(name)
        if path.exists():
            path.unlink()
            removed.append(name)

    return removed
