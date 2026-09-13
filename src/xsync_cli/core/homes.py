"""The isolated home of one harness.

A harness keeps its settings in a home directory. xSync makes one home
for each profile and each harness. The harness then runs against the
endpoint of the profile, and the real home of the user stays as it is.

The home holds its own settings and its own sessions. It links the
folders that hold the work of the user, such as the skills and the
plugins, so those stay in one place.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

# The folders and the files that both homes share. A session folder, a
# cache, and a log never appear here. Those hold state of one run.
SHARED_CODEX = ("skills", "plugins", "marketplaces", "memories", "AGENTS.md")
SHARED_CLAUDE = ("agents", "skills", "plugins", "hooks", "commands", "CLAUDE.md")


class HomeError(Exception):
    """The home cannot be made, or the harness cannot start."""


def homes_root() -> Path:
    """The folder that holds every isolated home."""
    from xsync_cli.core.profiles import default_store_path

    override = os.environ.get("XSYNC_PROFILES")
    base = Path(override).parent if override else default_store_path().parent
    return base / "homes"


def home_for(profile_name: str, harness: str) -> Path:
    """The home of one profile and one harness."""
    if not profile_name or "/" in profile_name or profile_name in (".", ".."):
        raise HomeError(
            f"the profile name {profile_name!r} cannot become a folder name."
        )
    return homes_root() / profile_name / harness


def link_shared(
    source_home: Path, target_home: Path, names: Sequence[str]
) -> list[str]:
    """Share the work of the user with the isolated home.

    A folder becomes a symbolic link. A file becomes a copy, because a
    harness writes a file back. The function never replaces a real
    folder in the target.
    """
    shared: list[str] = []
    for name in names:
        source = source_home / name
        if not source.exists():
            continue
        target = target_home / name

        if source.is_dir():
            if target.is_symlink():
                if target.resolve() == source.resolve():
                    shared.append(name)
                    continue
                target.unlink()
            elif target.exists():
                continue
            target.symlink_to(source, target_is_directory=True)
            shared.append(name)
        else:
            if target.exists() and not target.is_symlink():
                continue
            if target.is_symlink():
                target.unlink()
            shutil.copy2(source, target)
            shared.append(name)
    return shared


def _default_exec(command: str, argv: list[str], env: dict[str, str]) -> None:
    os.execvpe(command, argv, env)  # noqa: S606


def launch(
    command: str,
    home_variable: str,
    home: str,
    extra_args: Sequence[str],
    exec_fn: Callable[[str, list[str], dict[str, str]], None] | None = None,
) -> None:
    """Start the harness against the isolated home.

    The function replaces the xsync process. It does not return.
    """
    env = dict(os.environ)
    env[home_variable] = str(home)
    argv = [command, *extra_args]
    runner = exec_fn or _default_exec
    try:
        runner(command, argv, env)
    except FileNotFoundError:
        raise HomeError(
            f"the command {command!r} is not found. Install it, or add it to PATH."
        ) from None
