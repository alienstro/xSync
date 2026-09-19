"""The profile store.

A profile holds the connection data for one OpenAI-compatible endpoint.
The store keeps the profiles in a TOML file with mode 0600.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit

WIRE_APIS = ("chat", "responses")
ENDPOINT_TYPES = ("generic", "cliproxy")


class ProfileError(Exception):
    """The profile data is wrong, or the profile does not exist."""


def default_store_path() -> Path:
    """The default path of the profile file."""
    return Path.home() / ".config" / "xsync" / "profiles.toml"


@dataclass(frozen=True, slots=True)
class Profile:
    """One endpoint, with its filters."""

    name: str
    base_url: str
    api_key: str | None
    api_key_env: str | None
    wire_api: str
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    endpoint_type: str = "generic"

    def __post_init__(self) -> None:
        if self.api_key and self.api_key_env:
            raise ProfileError(
                f"profile {self.name!r} sets api_key and api_key_env. "
                "Set one, not both."
            )
        if self.wire_api not in WIRE_APIS:
            raise ProfileError(
                f"profile {self.name!r} has wire_api {self.wire_api!r}. "
                f"Use one of {', '.join(WIRE_APIS)}."
            )
        if self.endpoint_type not in ENDPOINT_TYPES:
            raise ProfileError(
                f"profile {self.name!r} has endpoint_type {self.endpoint_type!r}. "
                f"Use one of {', '.join(ENDPOINT_TYPES)}."
            )
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    def resolve_key(self, env: Mapping[str, str]) -> str | None:
        """The API key, or None when the profile has no key."""
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            value = env.get(self.api_key_env)
            if not value:
                raise ProfileError(
                    f"profile {self.name!r} needs the variable "
                    f"{self.api_key_env}. The variable is empty or absent."
                )
            return value
        return None

    def to_table(self) -> dict[str, object]:
        """The profile as plain data, without the name."""
        table: dict[str, object] = {
            "base_url": self.base_url,
            "wire_api": self.wire_api,
            "endpoint_type": self.endpoint_type,
        }
        if self.api_key:
            table["api_key"] = self.api_key
        if self.api_key_env:
            table["api_key_env"] = self.api_key_env
        if self.include:
            table["include"] = list(self.include)
        if self.exclude:
            table["exclude"] = list(self.exclude)
        return table


class ProfileStore:
    """The reader and the writer of the profile file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.active: str | None = None
        self._profiles: dict[str, Profile] = {}

    def load(self) -> None:
        """Read the file. An absent file gives an empty store."""
        if not self.path.exists():
            self.active = None
            self._profiles = {}
            return
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.active = data.get("active")
        self._profiles = {}
        for name, table in (data.get("profiles") or {}).items():
            self._profiles[name] = Profile(
                name=name,
                base_url=str(table.get("base_url", "")),
                api_key=table.get("api_key"),
                api_key_env=table.get("api_key_env"),
                wire_api=str(table.get("wire_api", "chat")),
                include=list(table.get("include", [])),
                exclude=list(table.get("exclude", [])),
                endpoint_type=str(table.get("endpoint_type", "generic")),
            )
        if self.active not in self._profiles:
            self.active = next(iter(self._profiles), None)

    def save(self) -> None:
        """Write the file with mode 0600."""
        document = tomlkit.document()
        if self.active:
            document["active"] = self.active
        profiles = tomlkit.table(is_super_table=True)
        for name, profile in self._profiles.items():
            entry = tomlkit.table()
            for key, value in profile.to_table().items():
                entry[key] = value
            profiles[name] = entry
        document["profiles"] = profiles

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def add(self, profile: Profile) -> None:
        """Add a profile. The first profile becomes the active profile."""
        self._profiles[profile.name] = profile
        if self.active is None:
            self.active = profile.name

    def get(self, name: str) -> Profile:
        """One profile by name."""
        try:
            return self._profiles[name]
        except KeyError:
            raise ProfileError(f"unknown profile {name!r}") from None

    def remove(self, name: str) -> None:
        """Delete a profile. Move the active name when necessary."""
        if name not in self._profiles:
            raise ProfileError(f"unknown profile {name!r}")
        del self._profiles[name]
        if self.active == name:
            self.active = next(iter(self._profiles), None)

    def names(self) -> list[str]:
        """The profile names, in insertion order."""
        return list(self._profiles)

    def set_active(self, name: str) -> None:
        """Make one profile the active profile."""
        if name not in self._profiles:
            raise ProfileError(f"unknown profile {name!r}")
        self.active = name

    def active_profile(self) -> Profile:
        """The active profile."""
        if not self.active:
            raise ProfileError("no profile exists. Run `xsync setup` first.")
        return self.get(self.active)
