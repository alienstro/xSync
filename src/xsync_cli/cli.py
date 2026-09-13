"""The xsync command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from xsync_cli.core.profiles import (
    WIRE_APIS,
    Profile,
    ProfileError,
    ProfileStore,
    default_store_path,
)
from xsync_cli.sources.openai_compat import (
    EndpointUnreachable,
    SourceError,
    fetch_models,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNREACHABLE = 2


def store_path() -> Path:
    """The profile file. The variable XSYNC_PROFILES wins."""
    override = os.environ.get("XSYNC_PROFILES")
    return Path(override) if override else default_store_path()


def open_store() -> ProfileStore:
    store = ProfileStore(store_path())
    store.load()
    return store


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_list(prompt: str) -> list[str]:
    answer = _ask(prompt)
    return [part.strip() for part in answer.split(",") if part.strip()]


def cmd_setup(args: argparse.Namespace) -> int:
    """Make a profile."""
    store = open_store()

    name = _ask("profile name")
    if not name:
        print("the profile name cannot be empty.", file=sys.stderr)
        return EXIT_ERROR

    base_url = _ask("base URL (for example http://127.0.0.1:20128/v1)")
    if not base_url:
        print("the base URL cannot be empty.", file=sys.stderr)
        return EXIT_ERROR

    api_key = _ask("API key (leave empty when the endpoint needs none)")
    include = _ask_list("include globs, separated by a comma (optional)")
    exclude = _ask_list("exclude globs, separated by a comma (optional)")

    print(f"testing {base_url}/models …")
    try:
        models = fetch_models(base_url, api_key or None)
    except EndpointUnreachable as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    except SourceError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    print(f"\n{len(models)} models:")
    for model in models:
        window = f"{model.context_window:,}" if model.context_window else "unknown"
        flags = ",".join(
            flag
            for flag, on in (
                ("tools", model.tools),
                ("reasoning", model.reasoning),
                ("vision", model.vision),
                ("search", model.search),
            )
            if on
        )
        print(f"  {model.slug:<48} {window:>12}  {flags}")

    print()
    wire_api = _ask(f"wire API ({' or '.join(WIRE_APIS)})", "chat")

    try:
        profile = Profile(
            name=name,
            base_url=base_url,
            api_key=api_key or None,
            api_key_env=None,
            wire_api=wire_api,
            include=include,
            exclude=exclude,
        )
    except ProfileError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    store.add(profile)
    store.save()
    print(f"\nsaved profile {name!r} to {store.path}")
    if store.active == name:
        print(f"profile {name!r} is now active")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    """Show the profiles."""
    store = open_store()
    if not store.names():
        print("no profile exists. Run `xsync setup` first.")
        return EXIT_OK
    for name in store.names():
        mark = "*" if name == store.active else " "
        profile = store.get(name)
        print(f"{mark} {name:<20} {profile.base_url:<40} {profile.wire_api}")
    return EXIT_OK


def cmd_use(args: argparse.Namespace) -> int:
    """Set the active profile."""
    store = open_store()
    try:
        store.set_active(args.name)
    except ProfileError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    store.save()
    print(f"active profile: {args.name}")
    return EXIT_OK


def cmd_remove(args: argparse.Namespace) -> int:
    """Delete a profile."""
    store = open_store()
    try:
        store.remove(args.name)
    except ProfileError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    store.save()
    print(f"removed profile {args.name!r}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xsync",
        description="Sync the model list of an OpenAI-compatible endpoint into a harness.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="make a profile").set_defaults(func=cmd_setup)
    sub.add_parser("list", help="show the profiles").set_defaults(func=cmd_list)

    use = sub.add_parser("use", help="set the active profile")
    use.add_argument("name")
    use.set_defaults(func=cmd_use)

    remove = sub.add_parser("remove", help="delete a profile")
    remove.add_argument("name")
    remove.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ProfileError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
