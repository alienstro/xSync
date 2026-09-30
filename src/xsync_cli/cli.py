"""The xsync command line."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from getpass import getpass
from pathlib import Path

from xsync_cli.adapters import claude_config, opencode_config, pi_config
from xsync_cli.adapters.codex import load_rules, render_catalog
from xsync_cli.adapters.isolated import (
    prepare_claude_home,
    prepare_codex_home,
    prepare_opencode_home,
    prepare_pi_family_home,
)
from xsync_cli.core import term
from xsync_cli.core.homes import (
    HomeError,
    home_for,
    homes_root,
    launch,
    launch_environment,
)
from xsync_cli.adapters.claude import load_rules as load_claude_rules
from xsync_cli.adapters.claude import render_rows
from xsync_cli.adapters.claude_config import (
    ClaudeConfigError,
    check_endpoint_match,
    current_rows,
    default_claude_home,
    init_settings,
    read_settings,
    settings_path_for,
    write_picker,
)
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
from xsync_cli.adapters.codex_wiring import (
    init_config,
    known_removals,
    reset_config,
    reset_defaults,
)
from xsync_cli.core.atomic import write_json_atomic
from xsync_cli.core.diff import diff_catalogs
from xsync_cli.core.filters import apply_filters
from xsync_cli.core.install import (
    InstallError,
    current_install,
    uninstall_commands,
    update_commands,
)
from xsync_cli.core.profiles import (
    ENDPOINT_TYPES,
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


def _endpoint_type(name: str, base_url: str, requested: str | None) -> str:
    """Select the endpoint compatibility mode."""
    if requested:
        return requested
    compact_name = "".join(
        character for character in name.lower() if character.isalnum()
    )
    if "cliproxy" in compact_name:
        return "cliproxy"
    address = base_url.rstrip("/")
    if address.endswith(":8317") or ":8317/" in address:
        return "cliproxy"
    return "generic"


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
    endpoint_type = _endpoint_type(name, base_url, args.endpoint_type)
    if endpoint_type == "cliproxy":
        print(f"   {term.dim('endpoint type:')} CLIProxy")

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

    # The endpoint picks the protocol, so setup does not ask for it.
    # xSync reuses the value that Codex already has for this URL.
    codex_home = default_codex_home()
    known = wire_api_for_url(read_config(codex_home / "config.toml"), base_url)
    wire_api = known or "responses"

    try:
        profile = Profile(
            name=name,
            base_url=base_url,
            api_key=api_key or None,
            api_key_env=None,
            wire_api=wire_api,
            include=include,
            exclude=exclude,
            endpoint_type=endpoint_type,
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
    print(f"   {term.bold('xsync codex')}      open Codex on this endpoint")
    print(f"   {term.bold('xsync claude')}     open Claude Code on this endpoint")
    print(f"   {term.bold('xsync opencode')}   open OpenCode on this endpoint")
    print(f"   {term.bold('xsync pi')}         open Pi on this endpoint")
    print(f"   {term.bold('xsync omp')}        open OMP on this endpoint\n")
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
        ("type", profile.endpoint_type),
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


def _stop_codex_daemon(
    codex_home: Path, assume_yes: bool, operation: str = "reset"
) -> bool:
    """Stop the target daemon before its model configuration changes."""
    socket_path = codex_home / "app-server-control" / "app-server-control.sock"
    if not socket_path.exists():
        return True

    print(term.yellow(
        f"   Caution: {operation.capitalize()} disconnects Codex sessions that use this home."
    ))
    if not assume_yes and not _confirm(
        f"Stop the Codex daemon and {operation} this home?"
    ):
        _fail("stopped. Nothing was removed. Use --yes to confirm in a script.")
        return False

    executable = shutil.which("codex")
    if executable is None:
        raise ConfigError(
            f"Codex is not on the PATH. Stop its daemon before {operation}."
        )
    environment = {**os.environ, "CODEX_HOME": str(codex_home)}
    try:
        # Daemon children can retain pipe handles after the command exits.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(
                [executable, "app-server", "daemon", "stop"],
                env=environment,
                stdout=stdout,
                stderr=stderr,
                timeout=15,
            )
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read().decode("utf-8", errors="replace")
            error_output = stderr.read().decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as error:
        detail = error.stderr or error.stdout or ""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise ConfigError(
            f"Cannot stop the Codex daemon after 15 seconds. "
            f"The {operation} did not change any files.\n{detail.strip()}"
        ) from error
    except OSError as error:
        raise ConfigError(
            f"Cannot stop the Codex daemon. The {operation} did not change any files.\n{error}"
        ) from error
    if result.returncode != 0:
        detail = (error_output or result.stderr or output or result.stdout or "").strip()
        raise ConfigError(
            f"Cannot stop the Codex daemon. The {operation} did not change any files.\n"
            f"{detail or f'Codex exited with code {result.returncode}.'}"
        )
    _ok("Stopped the Codex daemon for this home.")
    return True

def _do_reset(
    codex_home: Path, profile_name: str, force: bool, assume_yes: bool = False
) -> int:
    """Remove everything that xSync wrote."""
    state_path = codex_home / STATE_FILENAME
    state = read_state(state_path)
    print(term.dim(f"   home: {codex_home}"))

    if state is None:
        config = read_config(codex_home / "config.toml")
        providers = config.get("model_providers") or {}
        if (
            "model_catalog_json" not in config
            and config.get("model_provider", "openai") == "openai"
            and profile_name not in providers
        ):
            state = State(profile=profile_name)

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

    if not _stop_codex_daemon(codex_home, assume_yes):
        return EXIT_ERROR

    removed = (
        reset_config(codex_home / "config.toml", state)
        if state.keys_written or state.blocks_written or state.files_written
        else []
    )
    cache_path = codex_home / "models_cache.json"
    if cache_path.exists():
        cache_path.unlink()
        removed.append(str(cache_path))
    clear_state(state_path)
    print(term.heading("Reset"))
    print(term.rule())
    for name in removed:
        print(f"   {term.red('-')} {name}")
    print(term.rule())
    _ok("The Codex configuration is reset. The model cache is clear.")
    print(term.dim("   Restart the original Codex to load its model list."))
    print()
    return EXIT_OK


def _codex_reset_defaults(args: argparse.Namespace) -> int:
    """Reset all settings in the original Codex configuration."""
    if args.profile or args.init or args.reset or args.force or args.yolo or args.extra:
        _fail("Use only --yes or --dry-run with codex reset.")
        return EXIT_ERROR

    codex_home = default_codex_home()
    config_path = codex_home / "config.toml"
    print(term.heading("Reset Codex Defaults"))
    print(term.dim(f"   home: {codex_home}"))
    print(term.yellow("   Caution: Reset removes every setting in config.toml."))
    print(term.yellow("   Caution: Reset disconnects Codex sessions that use this home."))
    print(term.dim("   A dated backup preserves the current config.toml."))
    print(term.dim("   Authentication, sessions, skills, and plugin files stay."))

    if args.dry_run:
        print(term.dim("   The command would clear the configuration, model cache, and xSync state."))
        print(term.dim("   no file written (--dry-run)\n"))
        return EXIT_OK

    if not args.yes and not _confirm("Reset all Codex settings in this home?"):
        _fail("stopped. Nothing was removed. Use --yes to confirm in a script.")
        return EXIT_ERROR

    if not _stop_codex_daemon(codex_home, True):
        return EXIT_ERROR
    backup = reset_defaults(config_path)
    (codex_home / "models_cache.json").unlink(missing_ok=True)
    clear_state(codex_home / STATE_FILENAME)
    if backup is not None:
        _ok(f"Saved the configuration backup to {backup}")
    _ok("Cleared every setting in the original config.toml.")
    print(term.dim("   Restart the original Codex to load its default settings."))
    print()
    return EXIT_OK

def _codex_apply(args: argparse.Namespace) -> int:
    """Write the real Codex home."""
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

    # `--init` moves Codex to this profile, so a mismatch is expected then.
    if not args.init:
        try:
            message = check_provider_match(read_config(config_path), profile)
        except ConfigError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
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

    print(term.dim(f"   home: {codex_home}"))
    try:
        if not _stop_codex_daemon(codex_home, args.yes, "apply"):
            return EXIT_ERROR
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    # Write the catalog before the config refers to it. Codex does not
    # start when `model_catalog_json` names an absent file.
    write_json_atomic(catalog_path, catalog)
    _ok(
        f"wrote {term.bold(str(len(catalog['models'])))} models to "
        f"{term.dim(str(catalog_path))}"
    )

    if args.init:
        state_path = codex_home / STATE_FILENAME
        try:
            previous = read_state(state_path)
            state = init_config(config_path, profile, catalog_path, api_key)
        except ConfigError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
        write_state(state_path, _keep_first_values(state, previous))
        _ok(
            f"Codex now routes to {term.bold(profile.name)} "
            f"{term.dim('(' + profile.base_url + ')')}"
        )
    print(term.dim("   Restart the original Codex to load the updated model list."))
    print()
    return EXIT_OK


def _keep_first_values(state: State, previous: State | None) -> State:
    """Keep the values from before the first apply.

    A second apply sees the values of the first apply. The reset must put
    back the values from before xSync, so the older record wins.
    """
    if previous is None:
        return state
    replaced = {**state.keys_replaced, **previous.keys_replaced}
    return dataclasses.replace(state, keys_replaced=replaced)


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


HELP_GROUPS = (
    (
        "PROFILES",
        (
            ("setup", "make a profile, and read the model list"),
            ("list", "show the profiles. The active one has a dot"),
            ("use <name>", "set the active profile"),
            ("remove <name>", "delete a profile"),
        ),
    ),
    (
        "HARNESSES",
        (
            ("codex", "open a Codex on the profile, in its own home"),
            ("claude", "open a Claude Code the same way"),
            ("opencode", "open an OpenCode the same way"),
            ("pi", "open a Pi the same way"),
            ("omp", "open an OMP the same way"),
            ("<harness> apply", "write the real harness of the user"),
        ),
    ),
    (
        "INSTALL",
        (
            ("update", "update xsync with uv, pipx, or git"),
            ("uninstall", "reset the harnesses, then remove xsync"),
            ("uninstall --purge", "also delete the profiles and the keys"),
        ),
    ),
    (
        "HELP",
        (
            ("help", "show this page"),
            ("help <command>", "show the options of one command"),
        ),
    ),
)

HELP_OPTIONS = (
    ("--profile <name>", "use another profile for one run"),
    ("-- <args>", "send the arguments after -- to the harness"),
    ("--yolo", "start the harness with no permission question"),
    ("apply --dry-run", "show the difference. Write nothing"),
    ("apply --reset", "remove everything that xsync wrote"),
)

HELP_FILES = (
    ("~/.config/xsync/profiles.toml", "the profiles"),
    ("~/.config/xsync/homes/", "one home for each profile and harness"),
    ("~/.codex, ~/.claude", "only `apply` writes these"),
    ("~/.config/opencode", "only `apply` writes this"),
    ("~/.pi/agent, ~/.omp/agent", "only `apply` writes these"),
)

HELP_EXIT = (
    ("0", "success"),
    ("1", "an error"),
    ("2", "the endpoint does not answer"),
)


def _version() -> str:
    """The installed version of the tool."""
    try:
        from importlib.metadata import version

        return version("xsync-cli")
    except Exception:  # noqa: BLE001
        return "unknown"


def render_help() -> str:
    """The help page of the tool."""
    width = 43
    lines: list[str] = []

    lines.append("")
    lines.append(f"  {term.bold(term.cyan('xsync'))} {term.dim('v' + _version())}")
    lines.append(
        term.dim(
            "  Sync the models of an OpenAI-compatible endpoint into a harness."
        )
    )
    lines.append("")

    for title, rows in HELP_GROUPS:
        lines.append(f"  {term.bold(title)}")
        for name, text in rows:
            lines.append(f"    {term.pad(term.green(name), width)}{term.dim(text)}")
        lines.append("")

    lines.append(f"  {term.bold('OPTIONS')}")
    for name, text in HELP_OPTIONS:
        lines.append(f"    {term.pad(term.yellow(name), width)}{term.dim(text)}")
    lines.append("")

    lines.append(f"  {term.bold('FILES')}")
    for name, text in HELP_FILES:
        lines.append(f"    {term.pad(name, width)}{term.dim(text)}")
    lines.append("")

    lines.append(f"  {term.bold('EXIT CODES')}")
    codes = "   ".join(
        f"{term.bold(code)} {term.dim(text)}" for code, text in HELP_EXIT
    )
    lines.append(f"    {codes}")
    lines.append("")

    lines.append(f"  {term.dim('start here:')} {term.bold('xsync setup')}")
    lines.append("")
    return "\n".join(lines)



def cmd_help(args: argparse.Namespace) -> int:
    """Show the help of the tool, or the help of one command."""
    parser = build_parser()
    if not args.topic:
        print(render_help())
        return EXIT_OK

    actions = [
        action
        for action in parser._subparsers._group_actions  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    ]
    for action in actions:
        child = action.choices.get(args.topic)
        if child is not None:
            child.print_help()
            return EXIT_OK

    known = ", ".join(sorted(actions[0].choices)) if actions else ""
    _fail(f"unknown command {args.topic!r}. Known commands: {known}")
    return EXIT_ERROR


CLAUDE_MANAGED_KEYS = ("modelPicker", "env.ANTHROPIC_BASE_URL", "env.ANTHROPIC_AUTH_TOKEN")


def _claude_reset(claude_home: Path, profile_name: str, force: bool, yes: bool) -> int:
    """Remove everything that xSync wrote into the Claude settings."""
    state_path = claude_home / claude_config.STATE_FILENAME
    state = claude_config.read_state(state_path)

    if state is None:
        if not force:
            print(term.heading("Reset without a state file"))
            print(term.dim("   xsync did not record this setup. It would remove:"))
            for key in CLAUDE_MANAGED_KEYS:
                print(f"   {term.red('-')} {key}")
            _fail("add --force to continue.")
            return EXIT_ERROR
        print(term.heading("Reset without a state file"))
        for key in CLAUDE_MANAGED_KEYS:
            print(f"   {term.red('-')} {key}")
        if not yes and not _confirm(
            f"Remove the Claude Code setup of {profile_name!r}?"
        ):
            _fail("stopped. Nothing was removed.")
            return EXIT_ERROR
        state = claude_config.State(
            profile=profile_name, keys_written=list(CLAUDE_MANAGED_KEYS)
        )

    removed = claude_config.reset_settings(settings_path_for(claude_home), state)
    claude_config.clear_state(state_path)
    print(term.heading("Reset"))
    print(term.rule())
    for name in removed:
        print(f"   {term.red('-')} {name}")
    print(term.rule())
    _ok("Claude Code is back at its own defaults.")
    print()
    return EXIT_OK


def _claude_apply(args: argparse.Namespace) -> int:
    """Write the real Claude Code home."""
    store = open_store()
    claude_home = default_claude_home()
    settings_file = settings_path_for(claude_home)
    state_path = claude_home / claude_config.STATE_FILENAME

    try:
        profile = store.get(args.profile) if args.profile else store.active_profile()
    except ProfileError as error:
        _fail(str(error))
        return EXIT_ERROR

    if args.reset:
        try:
            return _claude_reset(claude_home, profile.name, args.force, args.yes)
        except ClaudeConfigError as error:
            _fail(str(error))
            return EXIT_ERROR

    keys_written: list[str] = []
    if args.init:
        try:
            api_key = profile.resolve_key(os.environ)
            state = init_settings(settings_file, profile, api_key)
        except (ClaudeConfigError, ProfileError) as error:
            _fail(str(error))
            return EXIT_ERROR
        keys_written = list(state.keys_written)
        _ok(
            f"Claude Code now talks to {term.bold(profile.name)} "
            f"{term.dim('(' + profile.base_url + ')')}"
        )

    try:
        api_key = profile.resolve_key(os.environ)
        models = fetch_models(profile.base_url, api_key)
    except EndpointUnreachable as error:
        _fail(str(error))
        return EXIT_UNREACHABLE
    except (SourceError, ProfileError) as error:
        _fail(str(error))
        return EXIT_ERROR

    models = apply_filters(models, profile.include, profile.exclude)

    try:
        settings = read_settings(settings_file)
    except ClaudeConfigError as error:
        _fail(str(error))
        return EXIT_ERROR

    message = check_endpoint_match(settings, profile)
    if message:
        if args.dry_run:
            _warn(message)
            print()
        else:
            _fail(message)
            return EXIT_ERROR

    rules = load_claude_rules()
    rows = render_rows(models, rules)
    _print_claude_report(rows, current_rows(settings), profile)

    if args.dry_run:
        print(term.dim("   no file written (--dry-run)\n"))
        return EXIT_OK

    try:
        write_picker(settings_file, rows)
    except ClaudeConfigError as error:
        _fail(str(error))
        return EXIT_ERROR

    keys_written.append("modelPicker")
    claude_config.write_state(
        state_path,
        claude_config.State(
            profile=profile.name,
            keys_written=sorted(set(keys_written)),
            settings_sha256=claude_config.file_sha256(settings_file),
            written_at=claude_config._now(),
        ),
    )
    _ok(
        f"wrote {term.bold(str(len(rows)))} models to "
        f"{term.dim(str(settings_file))}"
    )
    print(term.dim("   run /model in Claude Code to pick one\n"))
    return EXIT_OK


def _print_claude_report(rows, old_rows, profile: Profile) -> None:
    """Show the difference of one Claude sync."""
    print(term.heading(f"Sync {profile.name} → Claude Code"))
    print(term.dim(f"   {profile.base_url}"))
    print(term.rule())

    old = {row.get("model"): row for row in old_rows}
    new = {row["model"]: row for row in rows}

    added = [slug for slug in new if slug not in old]
    removed = [slug for slug in old if slug not in new]
    changed = [slug for slug in new if slug in old and new[slug] != old[slug]]
    unchanged = [slug for slug in new if slug in old and new[slug] == old[slug]]

    if not (added or removed or changed):
        _ok(f"up to date. {term.bold(str(len(rows)))} models, no change")
        return

    native = 0
    for slug in added:
        mapped = new[slug].get("behavesAs")
        note = term.dim(f"  (as {mapped})") if mapped else term.dim("  (native)")
        if not mapped:
            native += 1
        print(f"   {term.green('+')} {slug}{note}")
    for slug in removed:
        print(f"   {term.red('-')} {term.dim(slug)}")
    for slug in changed:
        print(f"   {term.yellow('~')} {slug}")

    print(term.rule())
    parts = []
    if added:
        parts.append(term.green(f"{len(added)} added"))
    if removed:
        parts.append(term.red(f"{len(removed)} removed"))
    if changed:
        parts.append(term.yellow(f"{len(changed)} changed"))
    parts.append(term.dim(f"{len(unchanged)} unchanged"))
    print("   " + "   ".join(parts))
    if native:
        print(term.dim(f"   {native} models keep their native Claude handling"))


def _opencode_reset(
    opencode_home: Path, profile_name: str, force: bool, yes: bool
) -> int:
    """Remove the provider that xSync wrote into OpenCode."""
    state_path = opencode_home / opencode_config.STATE_FILENAME
    state = opencode_config.read_state(state_path)

    if state is None:
        if not force:
            print(term.heading("Reset without a state file"))
            print(term.dim("   xsync did not record this setup. It would remove:"))
            print(f"   {term.red('-')} provider.{profile_name}")
            _fail("add --force to continue.")
            return EXIT_ERROR
        print(term.heading("Reset without a state file"))
        print(f"   {term.red('-')} provider.{profile_name}")
        if not yes and not _confirm(
            f"Remove the OpenCode setup of {profile_name!r}?"
        ):
            _fail("stopped. Nothing was removed.")
            return EXIT_ERROR
        state = opencode_config.State(
            profile=profile_name,
            provider_id=profile_name,
        )

    removed = opencode_config.reset_provider(
        opencode_config.config_path_for(opencode_home), state
    )
    opencode_config.clear_state(state_path)
    print(term.heading("Reset"))
    print(term.rule())
    for name in removed:
        print(f"   {term.red('-')} {name}")
    print(term.rule())
    _ok("OpenCode is back at its own defaults.")
    print()
    return EXIT_OK


def _opencode_apply(args: argparse.Namespace) -> int:
    """Write the real OpenCode configuration."""
    profile = _resolve_profile(args)
    if profile is None:
        return EXIT_ERROR

    opencode_home = opencode_config.default_opencode_home()
    config_path = opencode_config.config_path_for(opencode_home)
    state_path = opencode_home / opencode_config.STATE_FILENAME

    if args.reset:
        try:
            return _opencode_reset(
                opencode_home, profile.name, args.force, args.yes
            )
        except opencode_config.OpenCodeConfigError as error:
            _fail(str(error))
            return EXIT_ERROR

    models, code = _models_for(profile)
    if models is None:
        return code

    try:
        api_key = profile.resolve_key(os.environ)
        config = opencode_config.read_config(config_path)
    except (opencode_config.OpenCodeConfigError, ProfileError) as error:
        _fail(str(error))
        return EXIT_ERROR

    provider = opencode_config.render_provider(profile, api_key, models)
    current = opencode_config.current_provider(config, profile.name)
    _print_opencode_report(provider, current, profile)

    if args.dry_run:
        message = opencode_config.check_provider_match(config, profile)
        if message:
            print()
            _warn(message)
        print(term.dim("   no file written (--dry-run)\n"))
        return EXIT_OK

    try:
        state = opencode_config.write_provider(
            config_path, profile, api_key, models
        )
        opencode_config.write_state(state_path, state)
    except opencode_config.OpenCodeConfigError as error:
        _fail(str(error))
        return EXIT_ERROR

    _ok(
        f"wrote {term.bold(str(len(models)))} models to "
        f"{term.dim(str(config_path))}"
    )
    print(term.dim("   run /models in OpenCode to pick one\n"))
    return EXIT_OK


def _print_opencode_report(
    provider: dict, current: dict, profile: Profile
) -> None:
    """Show the difference of one OpenCode sync."""
    print(term.heading(f"Sync {profile.name} → OpenCode"))
    print(term.dim(f"   {profile.base_url}"))
    print(term.rule())

    old = current.get("models") if isinstance(current.get("models"), dict) else {}
    new = provider["models"]
    added = [slug for slug in new if slug not in old]
    removed = [slug for slug in old if slug not in new]
    changed = [slug for slug in new if slug in old and new[slug] != old[slug]]
    unchanged = [slug for slug in new if slug in old and new[slug] == old[slug]]

    if not (added or removed or changed):
        _ok(f"up to date. {term.bold(str(len(new)))} models, no change")
        return

    for slug in added:
        print(f"   {term.green('+')} {slug}")
    for slug in removed:
        print(f"   {term.red('-')} {term.dim(slug)}")
    for slug in changed:
        print(f"   {term.yellow('~')} {slug}")

    print(term.rule())
    parts = []
    if added:
        parts.append(term.green(f"{len(added)} added"))
    if removed:
        parts.append(term.red(f"{len(removed)} removed"))
    if changed:
        parts.append(term.yellow(f"{len(changed)} changed"))
    parts.append(term.dim(f"{len(unchanged)} unchanged"))
    print("   " + "   ".join(parts))


def _pi_family_home(harness: str) -> Path:
    """The real agent directory for Pi or OMP."""
    return (
        pi_config.default_pi_home()
        if harness == "pi"
        else pi_config.default_omp_home()
    )


def _pi_family_reset(
    home: Path,
    harness: str,
    profile_name: str,
    force: bool,
    yes: bool,
) -> int:
    """Remove one Pi-family provider block."""
    state_path = home / pi_config.STATE_FILENAME
    state = pi_config.read_state(state_path, harness)
    catalog_path = pi_config.catalog_path_for(home, harness)

    if state is None:
        if not force:
            print(term.heading("Reset without a state file"))
            print(term.dim("   xsync did not record this setup. It would remove:"))
            print(f"   {term.red('-')} providers.{profile_name}")
            _fail("add --force to continue.")
            return EXIT_ERROR
        print(term.heading("Reset without a state file"))
        print(f"   {term.red('-')} providers.{profile_name}")
        if not yes and not _confirm(
            f"Remove the {harness} setup of {profile_name!r}?"
        ):
            _fail("stopped. Nothing was removed.")
            return EXIT_ERROR
        state = pi_config.State(
            profile=profile_name,
            provider_id=profile_name,
            catalog_file=str(catalog_path),
        )
    elif state.catalog_file:
        catalog_path = Path(state.catalog_file)

    removed = pi_config.reset_provider(catalog_path, state)
    pi_config.clear_state(state_path, harness)
    print(term.heading("Reset"))
    print(term.rule())
    for name in removed:
        print(f"   {term.red('-')} {name}")
    print(term.rule())
    _ok(f"{harness} is back at its own defaults.")
    print()
    return EXIT_OK


def _pi_family_apply(args: argparse.Namespace, harness: str) -> int:
    """Write the real Pi or OMP model catalog."""
    profile = _resolve_profile(args)
    if profile is None:
        return EXIT_ERROR

    home = _pi_family_home(harness)
    catalog_path = pi_config.catalog_path_for(home, harness)
    state_path = home / pi_config.STATE_FILENAME

    if args.reset:
        try:
            return _pi_family_reset(
                home,
                harness,
                profile.name,
                args.force,
                args.yes,
            )
        except pi_config.PiConfigError as error:
            _fail(str(error))
            return EXIT_ERROR

    models, code = _models_for(profile)
    if models is None:
        return code

    try:
        api_key = profile.resolve_key(os.environ)
        catalog = pi_config.read_catalog(catalog_path)
    except (pi_config.PiConfigError, ProfileError) as error:
        _fail(str(error))
        return EXIT_ERROR

    provider = pi_config.render_provider(harness, profile, api_key, models)
    current = pi_config.current_provider(catalog, profile.name)
    _print_pi_family_report(harness, provider, current, profile)

    if args.dry_run:
        message = pi_config.check_provider_match(catalog, profile)
        if message:
            print()
            _warn(message)
        print(term.dim("   no file written (--dry-run)\n"))
        return EXIT_OK

    try:
        state = pi_config.write_provider(
            catalog_path,
            harness,
            profile,
            api_key,
            models,
        )
        pi_config.write_state(state_path, harness, state)
    except pi_config.PiConfigError as error:
        _fail(str(error))
        return EXIT_ERROR

    _ok(
        f"wrote {term.bold(str(len(models)))} models to "
        f"{term.dim(str(catalog_path))}"
    )
    print(term.dim(f"   run /model in {harness} to pick one\n"))
    return EXIT_OK


def _print_pi_family_report(
    harness: str,
    provider: dict,
    current: dict,
    profile: Profile,
) -> None:
    """Show the difference of one Pi-family sync."""
    print(term.heading(f"Sync {profile.name} → {harness}"))
    print(term.dim(f"   {profile.base_url}"))
    print(term.rule())

    old_rows = current.get("models")
    new_rows = provider["models"]
    old = {
        row.get("id"): row
        for row in old_rows
        if isinstance(row, dict) and row.get("id")
    } if isinstance(old_rows, list) else {}
    new = {row["id"]: row for row in new_rows}
    added = [slug for slug in new if slug not in old]
    removed = [slug for slug in old if slug not in new]
    changed = [slug for slug in new if slug in old and new[slug] != old[slug]]
    unchanged = [slug for slug in new if slug in old and new[slug] == old[slug]]
    settings_changed = any(
        current.get(key) != provider.get(key)
        for key in ("api", "apiKey", "auth", "baseUrl")
    )

    if not (added or removed or changed or settings_changed):
        _ok(f"up to date. {term.bold(str(len(new)))} models, no change")
        return

    if settings_changed:
        print(f"   {term.yellow('~')} provider settings")
    for slug in added:
        print(f"   {term.green('+')} {slug}")
    for slug in removed:
        print(f"   {term.red('-')} {term.dim(slug)}")
    for slug in changed:
        print(f"   {term.yellow('~')} {slug}")

    print(term.rule())
    parts = []
    if added:
        parts.append(term.green(f"{len(added)} added"))
    if removed:
        parts.append(term.red(f"{len(removed)} removed"))
    if changed:
        parts.append(term.yellow(f"{len(changed)} changed"))
    parts.append(term.dim(f"{len(unchanged)} unchanged"))
    print("   " + "   ".join(parts))


def _resolve_profile(args: argparse.Namespace):
    """The profile of this run, or None after an error."""
    store = open_store()
    try:
        return store.get(args.profile) if args.profile else store.active_profile()
    except ProfileError as error:
        _fail(str(error))
        return None


def _models_for(profile) -> tuple[list | None, int]:
    """The models of the endpoint, after the filters."""
    try:
        api_key = profile.resolve_key(os.environ)
        models = fetch_models(profile.base_url, api_key)
    except EndpointUnreachable as error:
        _fail(str(error))
        return None, EXIT_UNREACHABLE
    except (SourceError, ProfileError) as error:
        _fail(str(error))
        return None, EXIT_ERROR
    return apply_filters(models, profile.include, profile.exclude), EXIT_OK


# The flag that makes one harness skip every permission question.
# A user asks for it with `--yolo`.
YOLO_FLAG = {
    "codex": "--dangerously-bypass-approvals-and-sandbox",
    "claude": "--dangerously-skip-permissions",
    "opencode": "--auto",
    "pi": "--approve",
    "omp": "--yolo",
}


def _extra_args(args: argparse.Namespace, harness: str = "") -> list[str]:
    """The arguments that go to the harness."""
    extra = list(getattr(args, "extra", None) or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    flag = YOLO_FLAG.get(harness, "")
    if getattr(args, "yolo", False) and flag and flag not in extra:
        extra = [flag, *extra]
    return extra


def _open_harness(args: argparse.Namespace, harness: str) -> int:
    """Build the isolated home, then start the harness in it."""
    profile = _resolve_profile(args)
    if profile is None:
        return EXIT_ERROR

    models, code = _models_for(profile)
    if models is None:
        return code

    try:
        home = home_for(profile.name, harness)
    except HomeError as error:
        _fail(str(error))
        return EXIT_ERROR

    try:
        api_key = profile.resolve_key(os.environ)
    except ProfileError as error:
        _fail(str(error))
        return EXIT_ERROR

    environment: dict[str, str] | None = None
    if harness == "codex":
        prepare_codex_home(home, default_codex_home(), profile, api_key, models)
        command, variable = "codex", "CODEX_HOME"
    elif harness == "claude":
        prepare_claude_home(home, default_claude_home(), profile, api_key, models)
        command, variable = "claude", "CLAUDE_CONFIG_DIR"
    elif harness == "opencode":
        environment = prepare_opencode_home(
            home,
            opencode_config.default_opencode_home(),
            profile,
            api_key,
            models,
        )
        command, variable = "opencode", ""
    else:
        environment = prepare_pi_family_home(
            home,
            _pi_family_home(harness),
            harness,
            profile,
            api_key,
            models,
        )
        command, variable = harness, ""

    print(term.heading(f"{command} · {profile.name}"))
    print(term.dim(f"   {profile.base_url}"))
    print(term.dim(f"   home: {home}"))
    _ok(f"{term.bold(str(len(models)))} models ready. Your real {command} is untouched.")
    print()

    try:
        if environment is None:
            launch(command, variable, str(home), _extra_args(args, harness))
        else:
            launch_environment(command, environment, _extra_args(args, harness))
    except HomeError as error:
        _fail(str(error))
        return EXIT_ERROR
    return EXIT_OK


def cmd_codex(args: argparse.Namespace) -> int:
    """Open an isolated Codex, or write the real one."""
    if args.action is None and args.reset:
        args.action = "reset"
        args.reset = False
    if args.action == "reset":
        try:
            return _codex_reset_defaults(args)
        except (ConfigError, OSError) as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_ERROR
    if args.action == "apply":
        # `apply` writes the real home. It therefore wires the endpoint.
        # A dry run writes nothing, so it never wires anything.
        if not args.reset and not args.dry_run:
            args.init = True
        return _codex_apply(args)
    return _open_harness(args, "codex")


def cmd_claude(args: argparse.Namespace) -> int:
    """Open an isolated Claude Code, or write the real one."""
    if args.action == "apply":
        # `apply` writes the real home. It therefore wires the endpoint.
        # A dry run writes nothing, so it never wires anything.
        if not args.reset and not args.dry_run:
            args.init = True
        return _claude_apply(args)
    return _open_harness(args, "claude")


def cmd_opencode(args: argparse.Namespace) -> int:
    """Open an isolated OpenCode, or write the real one."""
    if args.action == "apply":
        return _opencode_apply(args)
    return _open_harness(args, "opencode")


def cmd_pi(args: argparse.Namespace) -> int:
    """Open an isolated Pi, or write the real one."""
    if args.action == "apply":
        return _pi_family_apply(args, "pi")
    return _open_harness(args, "pi")


def cmd_omp(args: argparse.Namespace) -> int:
    """Open an isolated OMP, or write the real one."""
    if args.action == "apply":
        return _pi_family_apply(args, "omp")
    return _open_harness(args, "omp")


def _add_harness_arguments(
    parser: argparse.ArgumentParser, *, allow_reset: bool = False
) -> None:
    """The arguments that both harness commands share."""
    parser.add_argument(
        "action",
        nargs="?",
        choices=["apply", "reset"] if allow_reset else ["apply"],
        help=(
            "apply writes the real home; reset restores all Codex settings to defaults"
            if allow_reset else "apply writes the real home of the harness"
        ),
    )
    parser.add_argument("--profile", help="use this profile for one run")
    parser.add_argument(
        "--dry-run", action="store_true", help="apply: show the difference only"
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="apply: point the harness at the endpoint (implied by apply)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help=(
            "without apply: reset all Codex settings; with apply: remove xsync settings"
            if allow_reset else "apply: remove everything xsync wrote"
        ),
    )
    parser.add_argument(
        "--force", action="store_true", help="apply: reset without a state file"
    )
    parser.add_argument(
        "--yes", action="store_true", help="confirm reset and the Codex daemon stop"
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="start the harness with no permission question. Use it with care",
    )
    parser.set_defaults(extra=[])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xsync",
        description="Sync the model list of an OpenAI-compatible endpoint into a harness.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    setup = sub.add_parser("setup", help="make a profile")
    setup.add_argument(
        "--endpoint-type",
        choices=ENDPOINT_TYPES,
        help="set the endpoint compatibility mode",
    )
    setup.set_defaults(func=cmd_setup)
    sub.add_parser("list", help="show the profiles").set_defaults(func=cmd_list)

    use = sub.add_parser("use", help="set the active profile")
    use.add_argument("name")
    use.set_defaults(func=cmd_use)

    remove = sub.add_parser("remove", help="delete a profile")
    remove.add_argument("name")
    remove.set_defaults(func=cmd_remove)

    codex = sub.add_parser(
        "codex",
        help="open an isolated Codex on the active profile",
        description=(
            "Open a Codex that talks to the endpoint of the profile. The real "
            "Codex of the user stays as it is. Add `apply` to write the real "
            "Codex instead. Add `reset` to restore all original Codex settings "
            "to defaults with a dated backup."
        ),
    )
    _add_harness_arguments(codex, allow_reset=True)
    codex.set_defaults(func=cmd_codex)

    claude = sub.add_parser(
        "claude",
        help="open an isolated Claude Code on the active profile",
        description=(
            "Open a Claude Code that talks to the endpoint of the profile. The "
            "real Claude Code of the user stays as it is. Add `apply` to write "
            "the real Claude Code instead."
        ),
    )
    _add_harness_arguments(claude)
    claude.set_defaults(func=cmd_claude)

    opencode = sub.add_parser(
        "opencode",
        help="open an isolated OpenCode on the active profile",
        description=(
            "Open an OpenCode that talks to the endpoint of the profile. The "
            "real OpenCode of the user stays as it is. Add `apply` to write "
            "the real OpenCode instead."
        ),
    )
    _add_harness_arguments(opencode)
    opencode.set_defaults(func=cmd_opencode)

    pi = sub.add_parser(
        "pi",
        help="open an isolated Pi on the active profile",
        description=(
            "Open a Pi that talks to the endpoint of the profile. The real "
            "Pi configuration stays as it is. Add `apply` to write the real "
            "Pi model catalog instead."
        ),
    )
    _add_harness_arguments(pi)
    pi.set_defaults(func=cmd_pi)

    omp = sub.add_parser(
        "omp",
        help="open an isolated OMP on the active profile",
        description=(
            "Open an OMP that talks to the endpoint of the profile. The real "
            "OMP configuration stays as it is. Add `apply` to write the real "
            "OMP model catalog instead."
        ),
    )
    _add_harness_arguments(omp)
    omp.set_defaults(func=cmd_omp)

    update = sub.add_parser(
        "update",
        help="update xsync with the tool that installed it",
        description=(
            "Update xsync. A git checkout gets a `git pull --ff-only` and a "
            "reinstall. An install from PyPI gets `uv tool upgrade` or "
            "`pipx upgrade`."
        ),
    )
    update.add_argument(
        "--dry-run", action="store_true", help="show the commands. Run nothing"
    )
    update.set_defaults(func=cmd_update)

    uninstall = sub.add_parser(
        "uninstall",
        help="reset the harnesses, then remove xsync",
        description=(
            "Reset every harness that `apply` wrote, then remove the xsync "
            "package. The profiles stay unless you add --purge."
        ),
    )
    uninstall.add_argument(
        "--purge",
        action="store_true",
        help="also delete the profiles, the API keys, and the isolated homes",
    )
    uninstall.add_argument(
        "--yes", action="store_true", help="do not ask for a confirmation"
    )
    uninstall.add_argument(
        "--dry-run", action="store_true", help="show the plan. Change nothing"
    )
    uninstall.set_defaults(func=cmd_uninstall)

    help_command = sub.add_parser("help", help="show this help, or the help of a command")
    help_command.add_argument("topic", nargs="?", help="a command name")
    help_command.set_defaults(func=cmd_help)

    return parser


def _run_command(command: list[str]) -> int:
    """Run one command in the terminal of the user and give its exit code."""
    return subprocess.run(command, check=False).returncode


def _command_output(command: list[str]) -> str:
    """Run one command and give its standard output."""
    return subprocess.run(
        command, check=False, capture_output=True, text=True
    ).stdout


def _missing_tools(commands: list[list[str]]) -> list[str]:
    """The programs of the commands that are not on the PATH."""
    names = dict.fromkeys(command[0] for command in commands)
    return [name for name in names if shutil.which(name) is None]


def _run_all(commands: list[list[str]]) -> bool:
    """Run the commands in order. Stop at the first failure."""
    for command in commands:
        print(term.dim(f"   $ {' '.join(command)}"))
        if _run_command(command) != 0:
            _fail(f"this command failed: {' '.join(command)}")
            return False
    return True


def cmd_update(args: argparse.Namespace) -> int:
    """Update xSync with the tool that installed it."""
    try:
        install = current_install(sys.prefix)
    except InstallError as error:
        _fail(str(error))
        return EXIT_ERROR

    has_git = install.source is not None and (Path(install.source) / ".git").exists()
    commands = update_commands(install, has_git)

    print(term.heading(f"Update xsync {_version()}"))
    for command in commands:
        print(f"   {' '.join(command)}")
    if args.dry_run:
        print(term.dim("\n   nothing ran (--dry-run)\n"))
        return EXIT_OK

    missing = _missing_tools(commands)
    if missing:
        _fail(f"install {', '.join(missing)} first. It is not on the PATH.")
        return EXIT_ERROR

    # A pull over local edits can mix them with the new code.
    if has_git and _command_output(
        ["git", "-C", install.source, "status", "--porcelain"]
    ).strip():
        _fail(
            f"{install.source} has uncommitted changes. "
            "Commit or stash them, then try again."
        )
        return EXIT_ERROR

    print()
    if not _run_all(commands):
        return EXIT_ERROR
    _ok("xsync is up to date. Run `xsync help` to see the version.")
    print()
    return EXIT_OK


def _applied_harnesses() -> list[tuple[str, Path, Callable[[], int]]]:
    """The harness homes that `apply` wrote, with the reset of each one.

    A home counts only when its state file exists. The reset then reads
    that file, so it needs no profile name.
    """
    found: list[tuple[str, Path, Callable[[], int]]] = []

    codex_home = default_codex_home()
    if (codex_home / STATE_FILENAME).exists():
        found.append(("codex", codex_home, lambda: _do_reset(codex_home, "", False, True)))

    claude_home = default_claude_home()
    if claude_config.read_state(claude_home / claude_config.STATE_FILENAME):
        found.append(
            ("claude", claude_home, lambda: _claude_reset(claude_home, "", False, True))
        )

    opencode_home = opencode_config.default_opencode_home()
    if (opencode_home / opencode_config.STATE_FILENAME).exists():
        found.append(
            (
                "opencode",
                opencode_home,
                lambda: _opencode_reset(opencode_home, "", False, True),
            )
        )

    for harness in ("pi", "omp"):
        home = _pi_family_home(harness)
        if pi_config.read_state(home / pi_config.STATE_FILENAME, harness):
            found.append(
                (
                    harness,
                    home,
                    lambda home=home, harness=harness: _pi_family_reset(
                        home, harness, "", False, True
                    ),
                )
            )
    return found


def _purge_targets() -> list[Path]:
    """The xSync data that --purge deletes."""
    profiles = Path(os.environ.get("XSYNC_PROFILES") or default_store_path())
    return [path for path in (profiles, homes_root()) if path.exists()]


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Reset every applied harness, then remove the xSync package."""
    try:
        install = current_install(sys.prefix)
    except InstallError as error:
        _fail(str(error))
        return EXIT_ERROR

    harnesses = _applied_harnesses()
    purge = _purge_targets() if args.purge else []
    commands = uninstall_commands(install)

    print(term.heading("Uninstall xsync"))
    print(term.rule())
    for name, home, _ in harnesses:
        print(f"   {term.yellow('~')} reset {name}  {term.dim(str(home))}")
    for path in purge:
        print(f"   {term.red('-')} delete {path}")
    for command in commands:
        print(f"   {term.red('-')} run {' '.join(command)}")
    if install.source:
        print(term.dim(f"   the source folder {install.source} stays"))
    if not args.purge:
        print(term.dim("   the profiles stay. Add --purge to delete them"))
    print(term.rule())

    if args.dry_run:
        print(term.dim("   nothing changed (--dry-run)\n"))
        return EXIT_OK

    missing = _missing_tools(commands)
    if missing:
        _fail(f"install {', '.join(missing)} first. It is not on the PATH.")
        return EXIT_ERROR

    if not args.yes and not _confirm("Continue?"):
        _fail("stopped. Nothing changed.")
        return EXIT_ERROR

    # Reset first. A failed reset stops before the package goes away, so
    # the user can fix it and run the command again.
    for name, _, reset in harnesses:
        if reset() != EXIT_OK:
            _fail(f"the reset of {name} failed. The package stays.")
            return EXIT_ERROR

    for path in purge:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for path in purge:
        # Remove the xsync folder too when nothing else is in it.
        with contextlib.suppress(OSError):
            path.parent.rmdir()

    if not _run_all(commands):
        return EXIT_ERROR
    _ok("xsync is removed.")
    print()
    return EXIT_OK


def _split_extra(argv: list[str]) -> tuple[list[str], list[str]]:
    """Cut the argument list at the first `--`.

    argparse reads the first part. The harness gets the second part.
    """
    if "--" not in argv:
        return argv, []
    cut = argv.index("--")
    return argv[:cut], argv[cut + 1 :]


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    mine, theirs = _split_extra(raw)
    parser = build_parser()
    args = parser.parse_args(mine)
    args.extra = theirs
    if not getattr(args, "command", None):
        print(render_help())
        return EXIT_OK
    try:
        return args.func(args)
    except (
        ProfileError,
        ConfigError,
        ClaudeConfigError,
        opencode_config.OpenCodeConfigError,
        pi_config.PiConfigError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
