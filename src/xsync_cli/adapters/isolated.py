"""The builder of an isolated harness home.

The functions here write into a home that xSync owns. They read the
real home of the user, but they never write into it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import tomlkit

from xsync_cli.adapters.claude import load_rules as load_claude_rules
from xsync_cli.adapters.claude import render_rows
from xsync_cli.adapters.codex import load_rules as load_codex_rules
from xsync_cli.adapters.codex import render_catalog
from xsync_cli.core.atomic import write_json_atomic
from xsync_cli.core.homes import SHARED_CLAUDE, SHARED_CODEX, link_shared
from xsync_cli.core.model import Model
from xsync_cli.core.profiles import Profile


def prepare_codex_home(
    home: Path,
    real_home: Path,
    profile: Profile,
    api_key: str | None,
    models: Sequence[Model],
) -> Path:
    """Build a Codex home that talks to the endpoint of the profile.

    The function copies the real `config.toml` as a base, so the trusted
    projects of the user stay. It then points the copy at the endpoint.
    """
    home.mkdir(parents=True, exist_ok=True)

    catalog_path = home / f"{profile.name}-models.json"
    write_json_atomic(
        catalog_path, render_catalog(models, load_codex_rules()), keep_backup=False
    )

    real_config = real_home / "config.toml"
    document = (
        tomlkit.parse(real_config.read_text(encoding="utf-8"))
        if real_config.exists()
        else tomlkit.document()
    )

    document["model_catalog_json"] = str(catalog_path)
    document["model_provider"] = profile.name

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

    temporary = home / "config.toml.tmp"
    temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
    os.replace(temporary, home / "config.toml")

    link_shared(real_home, home, SHARED_CODEX)
    return home


def prepare_claude_home(
    home: Path,
    real_home: Path,
    profile: Profile,
    api_key: str | None,
    models: Sequence[Model],
) -> Path:
    """Build a Claude Code home that talks to the endpoint.

    The function copies the real `settings.json` as a base, so the hooks
    of the user stay. It then adds the endpoint and the picker rows.
    """
    home.mkdir(parents=True, exist_ok=True)

    real_settings = real_home / "settings.json"
    settings: dict = {}
    if real_settings.exists():
        try:
            loaded = json.loads(real_settings.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings = loaded
        except json.JSONDecodeError:
            settings = {}

    environment = dict(settings.get("env") or {})
    environment["ANTHROPIC_BASE_URL"] = profile.base_url
    if api_key:
        environment["ANTHROPIC_AUTH_TOKEN"] = api_key
    settings["env"] = environment

    rows = render_rows(models, load_claude_rules())
    settings["modelPicker"] = {"options": rows, "replaceBuiltInOptions": False}

    temporary = home / "settings.json.tmp"
    temporary.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, home / "settings.json")

    link_shared(real_home, home, SHARED_CLAUDE)
    return home
