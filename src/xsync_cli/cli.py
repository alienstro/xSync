"""The xsync command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path

from xsync_cli.adapters.codex import load_rules, render_catalog
from xsync_cli.adapters.isolated import prepare_claude_home, prepare_codex_home
from xsync_cli.core import term
from xsync_cli.core.homes import HomeError, home_for, launch
from xsync_cli.adapters.claude import load_rules as load_claude_rules
from xsync_cli.adapters.claude import render_rows
from xsync_cli.adapters import claude_config
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
            ("<harness> apply", "write the real harness of the user"),
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
    width = 30
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

    if harness == "codex":
        prepare_codex_home(home, default_codex_home(), profile, api_key, models)
        command, variable = "codex", "CODEX_HOME"
    else:
        prepare_claude_home(home, default_claude_home(), profile, api_key, models)
        command, variable = "claude", "CLAUDE_CONFIG_DIR"

    print(term.heading(f"{command} · {profile.name}"))
    print(term.dim(f"   {profile.base_url}"))
    print(term.dim(f"   home: {home}"))
    _ok(f"{term.bold(str(len(models)))} models ready. Your real {command} is untouched.")
    print()

    try:
        launch(command, variable, str(home), _extra_args(args, harness))
    except HomeError as error:
        _fail(str(error))
        return EXIT_ERROR
    return EXIT_OK


def cmd_codex(args: argparse.Namespace) -> int:
    """Open an isolated Codex, or write the real one."""
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


def _add_harness_arguments(parser: argparse.ArgumentParser) -> None:
    """The arguments that both harness commands share."""
    parser.add_argument(
        "action",
        nargs="?",
        choices=["apply"],
        help="apply writes the real home of the harness",
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
        "--reset", action="store_true", help="apply: remove everything xsync wrote"
    )
    parser.add_argument(
        "--force", action="store_true", help="apply: reset without a state file"
    )
    parser.add_argument(
        "--yes", action="store_true", help="apply: answer yes to the reset question"
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

    sub.add_parser("setup", help="make a profile").set_defaults(func=cmd_setup)
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
            "Codex instead."
        ),
    )
    _add_harness_arguments(codex)
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

    help_command = sub.add_parser("help", help="show this help, or the help of a command")
    help_command.add_argument("topic", nargs="?", help="a command name")
    help_command.set_defaults(func=cmd_help)

    return parser


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
    except (ProfileError, ConfigError, ClaudeConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
