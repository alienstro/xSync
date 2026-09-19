"""Read and write Pi and OMP model catalogs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from xsync_cli.core.model import Model
from xsync_cli.core.profiles import Profile

STATE_FILENAME = ".xsync-state.json"
STATE_VERSION = 1


class PiConfigError(Exception):
    """A Pi-family catalog cannot be read or written."""


def default_pi_home() -> Path:
    """The Pi agent directory."""
    override = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(override) if override else Path.home() / ".pi" / "agent"


def default_omp_home() -> Path:
    """The OMP agent directory."""
    override = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(override) if override else Path.home() / ".omp" / "agent"


def catalog_path_for(home: Path, harness: str) -> Path:
    """The model catalog for one Pi-family harness."""
    if harness == "pi":
        return home / "models.json"
    yml = home / "models.yml"
    yaml_path = home / "models.yaml"
    return yaml_path if not yml.exists() and yaml_path.exists() else yml


def file_sha256(path: Path) -> str:
    """The hash of a file. An absent file gives an empty string."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_catalog(path: Path) -> dict[str, Any]:
    """Read a JSON or YAML model catalog."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = (
            json.loads(text)
            if path.suffix == ".json"
            else yaml.safe_load(text)
        )
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise PiConfigError(f"{path} is not valid catalog data: {error}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PiConfigError(f"{path} does not hold an object.")
    providers = data.get("providers")
    if providers is not None and not isinstance(providers, dict):
        raise PiConfigError(f"{path} has a non-object providers value.")
    return data


def _api_name(profile: Profile) -> str:
    if profile.wire_api == "chat":
        return "openai-completions"
    if profile.endpoint_type == "cliproxy":
        return "openai-codex-responses"
    return "openai-responses"


def _capability(model: Model, name: str) -> bool:
    reported = model.reported_capabilities
    if reported is None or name in reported:
        return bool(getattr(model, name))
    leaf = model.leaf_name.lower()
    if name == "reasoning":
        return leaf.startswith("gpt-5") or "codex" in leaf
    if name == "vision":
        return leaf.startswith("gpt-5")
    return False


def _model_entry(model: Model) -> dict[str, Any]:
    return {
        "id": model.slug,
        "name": model.slug,
        "reasoning": _capability(model, "reasoning"),
        "input": ["text", "image"] if _capability(model, "vision") else ["text"],
        "contextWindow": model.context_window or 128000,
        "maxTokens": model.max_output or 16384,
    }


def render_provider(
    harness: str,
    profile: Profile,
    api_key: str | None,
    models: list[Model],
) -> dict[str, Any]:
    """Build one Pi-family provider block."""
    provider: dict[str, Any] = {
        "baseUrl": profile.base_url,
        "api": _api_name(profile),
        "models": [_model_entry(model) for model in models],
    }
    if api_key:
        provider["apiKey"] = api_key
    elif harness == "omp":
        provider["auth"] = "none"
    else:
        provider["apiKey"] = "xsync-no-key"
    return provider


def current_provider(catalog: dict[str, Any], name: str) -> dict[str, Any]:
    """Return one provider block."""
    providers = catalog.get("providers")
    if not isinstance(providers, dict):
        return {}
    provider = providers.get(name)
    return dict(provider) if isinstance(provider, dict) else {}


def check_provider_match(catalog: dict[str, Any], profile: Profile) -> str | None:
    """Confirm that the provider uses the profile endpoint."""
    provider = current_provider(catalog, profile.name)
    base_url = provider.get("baseUrl")
    if not base_url:
        return f"the catalog has no provider named {profile.name!r}."
    if str(base_url).rstrip("/") != profile.base_url:
        return (
            f'the models would come from "{profile.name}" ({profile.base_url})\n'
            f"but the catalog uses {base_url}"
        )
    return None


@dataclass(frozen=True, slots=True)
class State:
    """The provider block that xSync wrote."""

    profile: str
    provider_id: str
    catalog_file: str
    catalog_sha256: str = ""
    written_at: str = ""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text_for(path: Path, catalog: dict[str, Any]) -> str:
    if path.suffix == ".json":
        text = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
        json.loads(text)
        return text
    text = yaml.safe_dump(
        catalog,
        allow_unicode=False,
        sort_keys=False,
        default_flow_style=False,
    )
    yaml.safe_load(text)
    return text


def _write_atomic(
    path: Path,
    catalog: dict[str, Any],
    before: str,
    keep_backup: bool = True,
) -> None:
    """Write the catalog only when the file did not change."""
    if file_sha256(path) != before:
        raise PiConfigError(f"{path} changed during the edit. Close the harness.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(_text_for(path, catalog), encoding="utf-8")
    os.chmod(temporary, 0o600)
    if keep_backup and path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, 0o600)
    os.replace(temporary, path)


def write_provider(
    path: Path,
    harness: str,
    profile: Profile,
    api_key: str | None,
    models: list[Model],
    keep_backup: bool = True,
) -> State:
    """Write one provider into a Pi-family catalog."""
    before = file_sha256(path)
    catalog = read_catalog(path)
    providers = dict(catalog.get("providers") or {})
    providers[profile.name] = render_provider(harness, profile, api_key, models)
    catalog["providers"] = providers
    _write_atomic(path, catalog, before, keep_backup=keep_backup)
    return State(
        profile=profile.name,
        provider_id=profile.name,
        catalog_file=str(path),
        catalog_sha256=file_sha256(path),
        written_at=_now(),
    )


def reset_provider(path: Path, state: State) -> list[str]:
    """Remove the provider block that the state records."""
    before = file_sha256(path)
    catalog = read_catalog(path)
    providers = catalog.get("providers")
    removed: list[str] = []
    if isinstance(providers, dict) and state.provider_id in providers:
        del providers[state.provider_id]
        removed.append(f"providers.{state.provider_id}")
        if not providers:
            del catalog["providers"]
    _write_atomic(path, catalog, before)
    return removed


def read_state(path: Path, harness: str) -> State | None:
    """Read the state for one Pi-family harness."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PiConfigError(f"{path} is not valid JSON: {error}") from None
    entry = data.get(harness) or {}
    if not entry:
        return None
    return State(
        profile=entry.get("profile", ""),
        provider_id=entry.get("provider_id", ""),
        catalog_file=entry.get("catalog_file", ""),
        catalog_sha256=entry.get("catalog_sha256", ""),
        written_at=entry.get("written_at", ""),
    )


def write_state(path: Path, harness: str, state: State) -> None:
    """Write the state for one Pi-family harness."""
    data: dict[str, Any] = {"version": STATE_VERSION}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(current, dict):
                data.update(current)
        except json.JSONDecodeError:
            pass
    data["version"] = STATE_VERSION
    data[harness] = asdict(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def clear_state(path: Path, harness: str) -> None:
    """Remove one harness entry from the state file."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        path.unlink()
        return
    data.pop(harness, None)
    if set(data) <= {"version"}:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
