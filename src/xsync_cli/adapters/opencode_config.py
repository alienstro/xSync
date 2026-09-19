"""Read and write the OpenCode provider configuration."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from xsync_cli.core.model import Model
from xsync_cli.core.profiles import Profile

STATE_FILENAME = ".xsync-state.json"
STATE_VERSION = 1


class OpenCodeConfigError(Exception):
    """The OpenCode configuration cannot be read or written."""


def default_opencode_home() -> Path:
    """The OpenCode global configuration directory."""
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "opencode"


def config_path_for(home: Path) -> Path:
    """The main OpenCode configuration file."""
    return home / "opencode.json"


def file_sha256(path: Path) -> str:
    """The hash of a file. An absent file gives an empty string."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_config(path: Path) -> dict[str, Any]:
    """Read an OpenCode JSON file."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise OpenCodeConfigError(f"{path} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise OpenCodeConfigError(f"{path} does not hold a JSON object.")
    return data


def _model_entry(model: Model) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": model.slug}
    limits: dict[str, int] = {}
    if model.context_window:
        limits["context"] = model.context_window
    if model.max_output:
        limits["output"] = model.max_output
    if limits:
        entry["limit"] = limits
    if (
        model.reported_capabilities is None
        or "reasoning" in model.reported_capabilities
    ):
        entry["reasoning"] = model.reasoning
    return entry


def render_provider(
    profile: Profile, api_key: str | None, models: list[Model]
) -> dict[str, Any]:
    """Build one OpenCode provider block."""
    package = (
        "@ai-sdk/openai"
        if profile.wire_api == "responses"
        else "@ai-sdk/openai-compatible"
    )
    options: dict[str, Any] = {"baseURL": profile.base_url}
    if api_key:
        options["apiKey"] = api_key
    return {
        "npm": package,
        "name": profile.name,
        "options": options,
        "models": {model.slug: _model_entry(model) for model in models},
    }


def current_provider(config: dict[str, Any], profile_name: str) -> dict[str, Any]:
    """Return the current provider block."""
    providers = config.get("provider")
    if not isinstance(providers, dict):
        return {}
    provider = providers.get(profile_name)
    return dict(provider) if isinstance(provider, dict) else {}


def check_provider_match(config: dict[str, Any], profile: Profile) -> str | None:
    """Confirm that OpenCode uses the endpoint of the profile."""
    provider = current_provider(config, profile.name)
    options = provider.get("options")
    base_url = options.get("baseURL") if isinstance(options, dict) else None
    if not base_url:
        return (
            "OpenCode has no provider for this profile.\n"
            f"run: xsync opencode apply --profile {profile.name}"
        )
    if str(base_url).rstrip("/") != profile.base_url:
        return (
            f'the models would come from "{profile.name}" ({profile.base_url})\n'
            f"but OpenCode uses {base_url}\n"
            f"run: xsync opencode apply --profile {profile.name}"
        )
    return None


@dataclass(frozen=True, slots=True)
class State:
    """The record of the provider block that xSync wrote."""

    profile: str
    provider_id: str
    config_sha256: str = ""
    written_at: str = ""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_atomic(path: Path, config: dict[str, Any], before: str) -> None:
    """Write the configuration only when the file did not change."""
    if file_sha256(path) != before:
        raise OpenCodeConfigError(
            f"{path} changed during the edit. Close OpenCode and try again."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    json.loads(text)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o600)
    if path.exists():
        path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
    os.replace(temporary, path)


def write_provider(
    path: Path,
    profile: Profile,
    api_key: str | None,
    models: list[Model],
) -> State:
    """Write one provider into the OpenCode configuration."""
    before = file_sha256(path)
    config = read_config(path)
    providers = dict(config.get("provider") or {})
    providers[profile.name] = render_provider(profile, api_key, models)
    config["provider"] = providers
    _write_atomic(path, config, before)
    return State(
        profile=profile.name,
        provider_id=profile.name,
        config_sha256=file_sha256(path),
        written_at=_now(),
    )


def reset_provider(path: Path, state: State) -> list[str]:
    """Remove the provider block that the state records."""
    before = file_sha256(path)
    config = read_config(path)
    providers = config.get("provider")
    removed: list[str] = []
    if isinstance(providers, dict) and state.provider_id in providers:
        del providers[state.provider_id]
        removed.append(f"provider.{state.provider_id}")
        if not providers:
            del config["provider"]
    _write_atomic(path, config, before)
    return removed


def read_state(path: Path) -> State | None:
    """Read the OpenCode state file."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise OpenCodeConfigError(f"{path} is not valid JSON: {error}") from None
    entry = data.get("opencode") or {}
    return State(
        profile=entry.get("profile", ""),
        provider_id=entry.get("provider_id", ""),
        config_sha256=entry.get("config_sha256", ""),
        written_at=entry.get("written_at", ""),
    )


def write_state(path: Path, state: State) -> None:
    """Write the OpenCode state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": STATE_VERSION, "opencode": asdict(state)}, indent=2),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def clear_state(path: Path) -> None:
    """Delete the OpenCode state file."""
    path.unlink(missing_ok=True)
