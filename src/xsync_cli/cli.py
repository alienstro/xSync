"""The xsync command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from xsync_cli.adapters.codex import load_rules, render_catalog
from xsync_cli.adapters.codex_config import (
    STATE_FILENAME,
    ConfigError,
    State,
    catalog_path_for,
    check_provider_match,
    clear_state,
    default_codex_home,
    read_config,
    read_state,
    write_state,
)
from xsync_cli.adapters.codex_wiring import init_config, known_removals, reset_config
from xsync_cli.core.atomic import write_json_atomic
from xsync_cli.core.diff import diff_catalogs
from xsync_cli.core.filters import apply_filters
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


def _load_catalog(path: Path) -> dict | None:
    """The current catalog, or None when it is absent or damaged."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _do_reset(codex_home: Path, profile_name: str, force: bool) -> int:
    """Remove everything that xSync wrote."""
    state_path = codex_home / STATE_FILENAME
    state = read_state(state_path)

    if state is None:
        planned = known_removals(profile_name)
        if not force:
            print("no state file exists. xSync would remove:")
            for key in planned.keys_written:
                print(f"  key    {key}")
            for block in planned.blocks_written:
                print(f"  block  [{block}]")
            print("\nadd --force to continue.", file=sys.stderr)
            return EXIT_ERROR
        state = State(
            profile=profile_name,
            keys_written=planned.keys_written,
            blocks_written=planned.blocks_written,
            files_written=[str(codex_home / f"{profile_name}-models.json")],
            config_sha256="",
            written_at="",
        )

    removed = reset_config(codex_home / "config.toml", state)
    clear_state(state_path)
    for name in removed:
        print(f"removed {name}")
    print("Codex is back at its own defaults.")
    return EXIT_OK


def cmd_codex(args: argparse.Namespace) -> int:
    """Sync a profile into the Codex catalog."""
    store = open_store()
    codex_home = default_codex_home()
    config_path = codex_home / "config.toml"

    try:
        profile = store.get(args.profile) if args.profile else store.active_profile()
    except ProfileError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    if args.reset:
        try:
            return _do_reset(codex_home, profile.name, args.force)
        except ConfigError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR

    catalog_path = catalog_path_for(profile, codex_home)

    if args.init:
        try:
            api_key = profile.resolve_key(os.environ)
            state = init_config(config_path, profile, catalog_path, api_key)
        except (ConfigError, ProfileError) as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
        write_state(codex_home / STATE_FILENAME, state)
        print(f"Codex now routes to {profile.name!r} ({profile.base_url})")

    try:
        api_key = profile.resolve_key(os.environ)
        models = fetch_models(profile.base_url, api_key)
    except EndpointUnreachable as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_UNREACHABLE
    except (SourceError, ProfileError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    models = apply_filters(models, profile.include, profile.exclude)

    config = read_config(config_path)
    message = check_provider_match(config, profile)
    if message:
        if args.dry_run:
            print(f"warning:\n{message}\n")
        else:
            print(f"error:\n{message}", file=sys.stderr)
            return EXIT_ERROR

    catalog = render_catalog(models, load_rules())
    report = diff_catalogs(_load_catalog(catalog_path), catalog)
    print(report.render())

    if args.dry_run:
        print("no files written (--dry-run)")
        return EXIT_OK

    write_json_atomic(catalog_path, catalog)
    print(f"wrote {len(catalog['models'])} models to {catalog_path}")
    return EXIT_OK


EPILOG = """\
examples:
  xsync setup                      make a profile, and read the model list
  xsync list                       show the profiles. The active one has a star
  xsync use openrouter             set the active profile
  xsync codex --init               connect Codex to the endpoint of the profile
  xsync codex --dry-run            show the difference. Write nothing
  xsync codex                      sync the models into the Codex catalog
  xsync codex --reset              remove everything that xsync wrote

files:
  ~/.config/xsync/profiles.toml    the profiles. `xsync setup` writes this file
  ~/.codex/<profile>-models.json   the Codex catalog that `xsync codex` writes
  ~/.codex/config.toml             only `--init` and `--reset` write this file

exit codes:
  0 success    1 error    2 the endpoint does not answer
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xsync",
        description="Sync the model list of an OpenAI-compatible endpoint into a harness.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("setup", help="make a profile").set_defaults(func=cmd_setup)
    sub.add_parser("list", help="show the profiles").set_defaults(func=cmd_list)

    use = sub.add_parser("use", help="set the active profile")
    use.add_argument("name")
    use.set_defaults(func=cmd_use)

    remove = sub.add_parser("remove", help="delete a profile")
    remove.add_argument("name")
    remove.set_defaults(func=cmd_remove)

    codex = sub.add_parser("codex", help="sync a profile into the Codex catalog")
    codex.add_argument("--profile", help="use this profile for one run")
    codex.add_argument("--dry-run", action="store_true", help="show the difference only")
    codex.add_argument("--init", action="store_true", help="wire Codex to the endpoint")
    codex.add_argument(
        "--reset", action="store_true", help="remove everything xSync wrote"
    )
    codex.add_argument("--force", action="store_true", help="reset without a state file")
    codex.set_defaults(func=cmd_codex)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK
    try:
        return args.func(args)
    except (ProfileError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
