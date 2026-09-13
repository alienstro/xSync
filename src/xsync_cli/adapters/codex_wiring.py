"""The writer of the Codex configuration.

Only `--init` and `--reset` use this module. The everyday sync does not
touch `config.toml`.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import tomlkit

from xsync_cli.adapters.codex_config import ConfigError, State, file_sha256
from xsync_cli.core.profiles import Profile

MANAGED_KEYS = ("model_catalog_json", "model_provider", "model")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    The function records every key and block that it writes. It does not
    record a key that already held a different value from another tool.
    """
    before = file_sha256(config_path)
    document = _load_document(config_path)

    keys_written: list[str] = []

    document["model_catalog_json"] = str(catalog_path)
    keys_written.append("model_catalog_json")

    existing_provider = document.get("model_provider")
    if existing_provider in (None, profile.name):
        document["model_provider"] = profile.name
        keys_written.append("model_provider")

    providers = document.get("model_providers")
    if providers is None:
        providers = tomlkit.table(is_super_table=True)
        document["model_providers"] = providers

    entry = tomlkit.table()
    entry["name"] = profile.name
    entry["base_url"] = profile.base_url
    entry["wire_api"] = profile.wire_api
    if api_key:
        headers = tomlkit.table()
        headers["Authorization"] = f"Bearer {api_key}"
        entry["http_headers"] = headers
    providers[profile.name] = entry

    _atomic_toml_write(config_path, document, before)

    return State(
        profile=profile.name,
        keys_written=keys_written,
        blocks_written=[f"model_providers.{profile.name}"],
        files_written=[str(catalog_path)],
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
        if key in document:
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
