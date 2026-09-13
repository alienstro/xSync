"""The xsync command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path

from xsync_cli.adapters.codex import load_rules, render_catalog
from xsync_cli.core import term
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
    wire_api_for_url,
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


def _ask(prompt: str, default: str = "", hint: str = "") -> str:
    """Ask one question. An empty answer gives the default."""
    if hint:
        print(term.dim(f"   {hint}"))
    suffix = term.dim(f" [{default}]") if default else ""
    answer = input(f"{term.cyan('?')} {term.bold(prompt)}{suffix}: ").strip()
    return answer or default


def _ask_secret(prompt: str, hint: str = "") -> str:
    """Ask for a secret. The terminal shows no character."""
    if hint:
        print(term.dim(f"   {hint}"))
    return getpass(f"{term.cyan('?')} {term.bold(prompt)}: ").strip()


def _ask_list(prompt: str, hint: str = "") -> list[str]:
    answer = _ask(prompt, hint=hint)
    return [part.strip() for part in answer.split(",") if part.strip()]


def _ok(text: str) -> None:
    print(f"{term.green('✓')} {text}")


def _warn(text: str) -> None:
    print(f"{term.yellow('!')} {text}")


def _fail(text: str) -> None:
    print(f"{term.red('✗')} {text}", file=sys.stderr)


def cmd_setup(args: argparse.Namespace) -> int:
    """Make a profile."""
    store = open_store()

    print(term.heading("New xsync profile"))
    print(term.rule())

    name = _ask("Profile name", hint="a short label, for example 9router")
    if not name:
        _fail("the profile name cannot be empty.")
        return EXIT_ERROR
    if name in store.names():
        _warn(f"the profile {name!r} exists. The answers replace it.")

    base_url = _ask(
        "Base URL", hint="the endpoint, for example http://127.0.0.1:20128/v1"
    )
    if not base_url:
        _fail("the base URL cannot be empty.")
        return EXIT_ERROR

    api_key = _ask_secret(
        "API key", hint="the terminal shows nothing. Press Enter when there is no key"
    )
    print(f"   {term.dim('key:')} {term.dim(term.mask_key(api_key))}")

    print(term.heading("Filters"))
    print(
        term.dim(
            "   A glob pattern selects models by name. The sign * means any\n"
            "   characters. Leave both empty to keep every model."
        )
    )
    include = _ask_list(
        "Include only these",
        hint="for example openai/*, *-mini    (empty keeps every model)",
    )
    exclude = _ask_list(
        "Exclude these", hint="for example *embedding*, *-image-*"
    )

    print(term.heading(f"Testing {base_url}/models"))
    try:
        models = fetch_models(base_url, api_key or None)
    except EndpointUnreachable as error:
        _fail(str(error))
        return EXIT_UNREACHABLE
    except SourceError as error:
        _fail(str(error))
        return EXIT_ERROR

    kept = apply_filters(models, include, exclude)
    _ok(f"the endpoint answered with {term.bold(str(len(models)))} models")
    if len(kept) != len(models):
        _ok(f"the filters keep {term.bold(str(len(kept)))} models")

    _print_model_table(kept)

    codex_home = default_codex_home()
    known = wire_api_for_url(read_config(codex_home / "config.toml"), base_url)
    print(term.heading("Wire API"))
    if known:
        print(
            term.dim(
                f"   Codex already talks to this URL with {known!r}. "
                "Press Enter to keep it."
            )
        )
    else:
        print(
            term.dim(
                "   Use chat for most OpenAI-compatible servers.\n"
                "   Use responses for the OpenAI Responses API.\n"
                "   A wrong value breaks every request."
            )
        )
    wire_api = _ask(f"Wire API ({' or '.join(WIRE_APIS)})", known or "chat")
    if known and wire_api != known:
        _warn(
            f"Codex uses {known!r} for this URL. The answer {wire_api!r} "
            "disagrees with it."
        )

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
        _fail(str(error))
        return EXIT_ERROR

    store.add(profile)
    store.save()

    print(term.heading("Saved"))
    print(term.rule())
    _print_profile(profile, active=store.active == profile.name)
    print(term.dim(f"\n   file: {store.path}"))
    print(term.heading("Next"))
    print(f"   {term.bold('xsync codex --init')}     connect Codex to this endpoint")
    print(f"   {term.bold('xsync codex --dry-run')}  see what would change")
    print(f"   {term.bold('xsync codex')}            write the catalog\n")
    return EXIT_OK


def _print_model_table(models: list) -> None:
    """Show the models in a table."""
    if not models:
        _warn("no model passes the filters.")
        return
    slug_size = max(len(m.slug) for m in models)
    print()
    print(
        "   "
        + term.dim(term.pad("MODEL", slug_size))
        + term.dim("  " + "CONTEXT".rjust(12))
        + term.dim("  FEATURES")
    )
    for model in models:
        window = f"{model.context_window:,}" if model.context_window else "—"
        flags = " ".join(
            term.green(flag)
            for flag, on in (
                ("tools", model.tools),
                ("reason", model.reasoning),
                ("vision", model.vision),
                ("search", model.search),
            )
            if on
        )
        print(
            "   "
            + term.pad(model.slug, slug_size)
            + "  "
            + window.rjust(12)
            + "  "
            + (flags or term.dim("—"))
        )
    print()


def _print_profile(profile: Profile, active: bool) -> None:
    """Show one profile as a block."""
    mark = term.green("●") if active else term.dim("○")
    label = term.bold(profile.name) + (term.dim("  (active)") if active else "")
    print(f"{mark} {label}")
    rows = [
        ("url", profile.base_url),
        ("key", term.mask_key(profile.api_key)
            if profile.api_key
            else (f"${profile.api_key_env}" if profile.api_key_env else "(none)")),
        ("wire api", profile.wire_api),
    ]
    if profile.include:
        rows.append(("include", ", ".join(profile.include)))
    if profile.exclude:
        rows.append(("exclude", ", ".join(profile.exclude)))
    for key, value in rows:
        print(f"   {term.dim(key.ljust(9))} {value}")


def cmd_list(args: argparse.Namespace) -> int:
    """Show the profiles."""
    store = open_store()
    if not store.names():
        print(term.heading("No profile"))
        print(f"   run {term.bold('xsync setup')} to make one.\n")
        return EXIT_OK
    print(term.heading("Profiles"))
    print(term.rule())
    for name in store.names():
        _print_profile(store.get(name), active=name == store.active)
        print()
    print(term.dim(f"   file: {store.path}\n"))
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


def _confirm(question: str) -> bool:
    """Ask for a yes. A pipe or a missing terminal gives no."""
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return False
    answer = input(f"{term.yellow('?')} {term.bold(question)} {term.dim('[yes/no]')}: ")
    return answer.strip().lower() in ("y", "yes")


def _do_reset(
    codex_home: Path, profile_name: str, force: bool, assume_yes: bool = False
) -> int:
    """Remove everything that xSync wrote."""
    state_path = codex_home / STATE_FILENAME
    state = read_state(state_path)

    if state is None:
        planned = known_removals(profile_name)
        if not force:
            print(term.heading("Reset without a state file"))
            print(term.dim("   xsync would remove:"))
            for key in planned.keys_written:
                print(f"   {term.red('-')} key    {key}")
            for block in planned.blocks_written:
                print(f"   {term.red('-')} block  [{block}]")
            _fail("add --force to continue.")
            return EXIT_ERROR
        print(term.heading("Reset without a state file"))
        print(term.dim("   xsync did not record this setup. It would remove:"))
        for key in planned.keys_written:
            print(f"   {term.red('-')} key    {key}")
        for block in planned.blocks_written:
            print(f"   {term.red('-')} block  [{block}]")
        print(term.dim("\n   The catalog backup <name>.bak stays on the disk."))
        if not assume_yes and not _confirm(
            f"Remove the Codex setup of {profile_name!r}?"
        ):
            _fail("stopped. Nothing was removed.")
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
    print(term.heading("Reset"))
    print(term.rule())
    for name in removed:
        print(f"   {term.red('-')} {name}")
    print(term.rule())
    _ok("Codex is back at its own defaults.")
    print()
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
            return _do_reset(codex_home, profile.name, args.force, args.yes)
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
        _ok(
            f"Codex now routes to {term.bold(profile.name)} "
            f"{term.dim('(' + profile.base_url + ')')}"
        )

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
            _warn(message)
            print()
        else:
            _fail(message)
            return EXIT_ERROR

    catalog = render_catalog(models, load_rules())
    report = diff_catalogs(_load_catalog(catalog_path), catalog)
    _print_report(report, profile, len(catalog["models"]))

    if args.dry_run:
        print(term.dim("   no file written (--dry-run)\n"))
        return EXIT_OK

    write_json_atomic(catalog_path, catalog)
    _ok(
        f"wrote {term.bold(str(len(catalog['models'])))} models to "
        f"{term.dim(str(catalog_path))}"
    )
    print()
    return EXIT_OK


def _print_report(report, profile: Profile, total: int) -> None:
    """Show the difference of one sync."""
    print(term.heading(f"Sync {profile.name} → Codex"))
    print(term.dim(f"   {profile.base_url}"))
    print(term.rule())

    if report.is_empty:
        _ok(f"up to date. {term.bold(str(total))} models, no change")
        return

    for slug in report.added:
        print(f"   {term.green('+')} {slug}")
    for slug in report.removed:
        print(f"   {term.red('-')} {term.dim(slug)}")
    for slug, fields in report.changed:
        head = ", ".join(fields[:3])
        more = f" +{len(fields) - 3} more" if len(fields) > 3 else ""
        print(f"   {term.yellow('~')} {slug}{term.dim(f'  ({head}{more})')}")

    print(term.rule())
    parts = []
    if report.added:
        parts.append(term.green(f"{len(report.added)} added"))
    if report.removed:
        parts.append(term.red(f"{len(report.removed)} removed"))
    if report.changed:
        parts.append(term.yellow(f"{len(report.changed)} changed"))
    parts.append(term.dim(f"{len(report.unchanged)} unchanged"))
    print("   " + "   ".join(parts))


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
    codex.add_argument(
        "--yes", action="store_true", help="answer yes to the reset question"
    )
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
