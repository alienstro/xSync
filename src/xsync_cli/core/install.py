"""How xSync was installed, and the commands that update or remove it.

xSync never replaces its own files. The tool that installed it (uv or
pipx) does the update and the removal, so its records stay correct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import metadata
from pathlib import PurePath
from urllib.parse import unquote, urlparse

PACKAGE = "xsync-cli"


class InstallError(Exception):
    """xSync cannot find how it was installed."""


@dataclass(frozen=True, slots=True)
class Install:
    """One install of xSync."""

    tool: str
    # The local folder of the install, or None for an install from an index.
    source: str | None
    editable: bool


def detect_install(direct_url: str | None, prefix: str) -> Install:
    """Find the install from the PEP 610 record and the environment prefix."""
    parts = PurePath(prefix).parts
    if "tools" in parts and "uv" in parts:
        tool = "uv"
    elif "venvs" in parts and "pipx" in parts:
        tool = "pipx"
    else:
        raise InstallError(
            f"xsync runs from {prefix}, which is not a uv or pipx tool. "
            "Update or remove it with the tool that installed it."
        )

    if not direct_url:
        return Install(tool, None, editable=False)
    record = json.loads(direct_url)
    url = urlparse(record.get("url", ""))
    if url.scheme != "file":
        return Install(tool, None, editable=False)
    editable = bool((record.get("dir_info") or {}).get("editable"))
    return Install(tool, unquote(url.path), editable=editable)


def current_install(prefix: str) -> Install:
    """The install of the running xSync."""
    try:
        direct_url = metadata.distribution(PACKAGE).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        raise InstallError(f"the package {PACKAGE} is not installed.") from None
    return detect_install(direct_url, prefix)


def update_commands(install: Install, has_git: bool) -> list[list[str]]:
    """The commands that update xSync, in order."""
    if install.source is None:
        if install.tool == "uv":
            return [["uv", "tool", "upgrade", PACKAGE]]
        return [["pipx", "upgrade", PACKAGE]]

    commands = []
    if has_git:
        commands.append(["git", "-C", install.source, "pull", "--ff-only"])
    editable = ["--editable"] if install.editable else []
    if install.tool == "uv":
        commands.append(
            ["uv", "tool", "install", "--force", "--reinstall", *editable, install.source]
        )
    else:
        commands.append(["pipx", "install", "--force", *editable, install.source])
    return commands


def uninstall_commands(install: Install) -> list[list[str]]:
    """The commands that remove the xSync package."""
    if install.tool == "uv":
        return [["uv", "tool", "uninstall", PACKAGE]]
    return [["pipx", "uninstall", PACKAGE]]
