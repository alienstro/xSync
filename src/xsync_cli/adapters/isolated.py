"""The builder of an isolated harness home.

The functions here write into a home that xSync owns. They read the
real home of the user, but they never write into it.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import tomlkit

from xsync_cli.adapters.claude import load_rules as load_claude_rules
from xsync_cli.adapters.claude import render_rows
from xsync_cli.adapters.codex import load_rules as load_codex_rules
from xsync_cli.adapters.codex import render_catalog
from xsync_cli.adapters.codex_wiring import provider_entry
from xsync_cli.adapters.opencode_config import render_provider
from xsync_cli.adapters import claude_config, pi_config
from xsync_cli.core.atomic import write_json_atomic
from xsync_cli.core.homes import (
    SHARED_CLAUDE,
    SHARED_CODEX,
    SHARED_OPENCODE,
    SHARED_PI_FAMILY,
    link_shared,
)
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

    providers[profile.name] = provider_entry(profile, api_key)

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

    environment, _ = claude_config.endpoint_environment(
        settings.get("env"),
        profile,
        api_key,
    )
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


def prepare_opencode_home(
    home: Path,
    real_home: Path,
    profile: Profile,
    api_key: str | None,
    models: Sequence[Model],
) -> dict[str, str]:
    """Build an isolated OpenCode environment."""
    home.mkdir(parents=True, exist_ok=True)
    config_root = home / "config"
    config_home = config_root / "opencode"
    config_home.mkdir(parents=True, exist_ok=True)

    if real_home.exists():
        for source in real_home.iterdir():
            if not source.is_file() or source.name == ".xsync-state.json":
                continue
            target = config_home / source.name
            if target.is_symlink():
                target.unlink()
            shutil.copy2(source, target)

    link_shared(real_home, config_home, SHARED_OPENCODE)

    overlay = home / "xsync-opencode.json"
    write_json_atomic(
        overlay,
        {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                profile.name: render_provider(profile, api_key, list(models))
            },
        },
        keep_backup=False,
    )
    os.chmod(overlay, 0o600)

    return {
        "OPENCODE_CONFIG": str(overlay),
        "XDG_CONFIG_HOME": str(config_root),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"),
    }


def prepare_pi_family_home(
    home: Path,
    real_home: Path,
    harness: str,
    profile: Profile,
    api_key: str | None,
    models: Sequence[Model],
) -> dict[str, str]:
    """Build an isolated Pi or OMP agent directory."""
    home.mkdir(parents=True, exist_ok=True)
    skipped = {
        ".xsync-state.json",
        "models.json",
        "models.yml",
        "models.yaml",
    }
    if real_home.exists():
        for source in real_home.iterdir():
            name = source.name
            if not source.is_file() or name in skipped:
                continue
            if ".db" in name or name.endswith(".lock"):
                continue
            target = home / name
            if target.is_symlink():
                target.unlink()
            shutil.copy2(source, target)

    link_shared(real_home, home, SHARED_PI_FAMILY)
    catalog_path = pi_config.catalog_path_for(home, harness)
    pi_config.write_provider(
        catalog_path,
        harness,
        profile,
        api_key,
        list(models),
        keep_backup=False,
    )

    xdg_root = home / "xdg"
    for kind in ("data", "cache", "state"):
        for name in ("omp", "pi"):
            (xdg_root / kind / name).mkdir(parents=True, exist_ok=True)

    return {
        "PI_CODING_AGENT_DIR": str(home),
        "PI_CODING_AGENT_SESSION_DIR": str(home / "sessions"),
        "XDG_DATA_HOME": str(xdg_root / "data"),
        "XDG_CACHE_HOME": str(xdg_root / "cache"),
        "XDG_STATE_HOME": str(xdg_root / "state"),
    }
