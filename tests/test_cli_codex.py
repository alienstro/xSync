import json
import subprocess
import tomllib

import pytest

from xsync_cli import cli
from xsync_cli.sources.openai_compat import parse_models


@pytest.fixture
def home(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        'active = "p"\n\n[profiles.p]\n'
        'base_url = "http://h/v1"\nwire_api = "chat"\napi_key = "sk-1"\n'
    )
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        'model_provider = "p"\n\n[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    monkeypatch.setenv("XSYNC_PROFILES", str(profiles))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    return codex


def stub(slugs):
    def fetch(base_url, api_key, timeout=10.0, retries=2, opener=None):
        return parse_models({"data": [{"id": s} for s in slugs]})

    return fetch


def test_sync_writes_the_catalog(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    assert cli.main(["codex", "apply"]) == 0
    catalog = json.loads((home / "p-models.json").read_text())
    assert [e["slug"] for e in catalog["models"]] == ["a/one", "b/two"]


def test_dry_run_writes_nothing(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--dry-run"]) == 0
    assert not (home / "p-models.json").exists()
    assert "no file written" in capsys.readouterr().out


def test_the_report_names_the_added_models(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "apply", "--dry-run"])
    assert "2 added" in capsys.readouterr().out


def test_a_second_sync_reports_the_difference(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "apply"])
    capsys.readouterr()
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "c/three"]))
    cli.main(["codex", "apply"])
    out = capsys.readouterr().out
    assert "1 added" in out
    assert "1 removed" in out


def test_the_exclude_rule_drops_a_model(home, monkeypatch):
    path = home.parent / "profiles.toml"
    path.write_text(
        'active = "p"\n\n[profiles.p]\n'
        'base_url = "http://h/v1"\nwire_api = "chat"\nexclude = ["*embedding*"]\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "a/text-embedding-3"]))
    cli.main(["codex", "apply"])
    catalog = json.loads((home / "p-models.json").read_text())
    assert [e["slug"] for e in catalog["models"]] == ["a/one"]


def test_apply_switches_codex_from_another_provider(home, monkeypatch):
    (home / "config.toml").write_text(
        'model_provider = "other"\n\n[model_providers.other]\n'
        'base_url = "https://other/v1"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 0
    config = tomllib.loads((home / "config.toml").read_text())
    assert config["model_provider"] == "p"
    assert config["model_catalog_json"] == str(home / "p-models.json")
    assert (home / "p-models.json").exists()


def test_a_failed_fetch_leaves_the_config_unchanged(home, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    before = (home / "config.toml").read_text()
    monkeypatch.setattr(cli, "fetch_models", failing)
    assert cli.main(["codex", "apply"]) == 2
    assert (home / "config.toml").read_text() == before
    assert not (home / ".xsync-state.json").exists()


def test_a_mismatch_only_warns_on_a_dry_run(home, monkeypatch):
    (home / "config.toml").write_text(
        'model_provider = "other"\n\n[model_providers.other]\n'
        'base_url = "https://other/v1"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--dry-run"]) == 0


def test_an_unreachable_endpoint_gives_exit_code_2(home, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    monkeypatch.setattr(cli, "fetch_models", failing)
    assert cli.main(["codex", "apply"]) == 2


def test_init_writes_the_provider_block(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--init"]) == 0
    text = (home / "config.toml").read_text()
    assert "[model_providers.p]" in text
    assert "model_catalog_json" in text
    assert (home / ".xsync-state.json").exists()


def test_reset_targets_the_original_home_inside_an_xsync_session(
    home, monkeypatch, capsys
):
    real_home = home.parent / ".codex"
    real_home.mkdir()
    (real_home / "config.toml").write_text('model_reasoning_effort = "high"\n')
    monkeypatch.setenv("HOME", str(home.parent))
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 0
    cache = real_home / "models_cache.json"
    cache.write_text('{"models": [{"slug": "stale"}]}')

    isolated = home.parent / "homes" / "p" / "codex"
    isolated.mkdir(parents=True)
    isolated_config = isolated / "config.toml"
    isolated_config.write_text('model_provider = "p"\n')
    monkeypatch.setenv("CODEX_HOME", str(isolated))
    capsys.readouterr()

    assert cli.main(["codex", "apply", "--reset"]) == 0

    config = tomllib.loads((real_home / "config.toml").read_text())
    assert "model_catalog_json" not in config
    assert "model_provider" not in config
    assert config["model_reasoning_effort"] == "high"
    assert not cache.exists()
    assert not (real_home / "p-models.json").exists()
    assert isolated_config.read_text() == 'model_provider = "p"\n'
    assert str(real_home) in capsys.readouterr().out

def test_reset_clears_the_cache_when_the_config_is_already_clean(home):
    config_path = home / "config.toml"
    config_path.write_text('model_reasoning_effort = "high"\n')
    cache = home / "models_cache.json"
    cache.write_text('{"models": [{"slug": "stale"}]}')
    sessions = home / "sessions"
    sessions.mkdir()
    session = sessions / "session.jsonl"
    session.write_text("keep this session\n")

    assert cli.main(["codex", "apply", "--reset"]) == 0
    assert not cache.exists()
    assert config_path.read_text() == 'model_reasoning_effort = "high"\n'
    assert session.read_text() == "keep this session\n"
    assert cli.main(["codex", "apply", "--reset"]) == 0

def test_reset_clears_the_cache_in_an_explicit_custom_home(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 0
    cache = home / "models_cache.json"
    cache.write_text('{"models": [{"slug": "stale"}]}')

    assert cli.main(["codex", "apply", "--reset"]) == 0
    assert not cache.exists()

def test_reset_clears_the_endpoint_model_selection(home, monkeypatch):
    (home / "config.toml").write_text('model_reasoning_effort = "high"\n')
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 0
    config_path = home / "config.toml"
    config_path.write_text('model = "a/one"\n' + config_path.read_text())

    assert cli.main(["codex", "apply", "--reset"]) == 0

    config = tomllib.loads(config_path.read_text())
    assert "model" not in config
    assert config["model_reasoning_effort"] == "high"

def test_reset_keeps_a_restored_provider_and_its_model(home, monkeypatch):
    original = (
        'model_provider = "other"\nmodel = "other-model"\n'
        'model_catalog_json = "/other-models.json"\n'
        '[model_providers.other]\nbase_url = "https://other/v1"\n'
    )
    (home / "config.toml").write_text(original)
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 0

    assert cli.main(["codex", "apply", "--reset"]) == 0
    assert tomllib.loads((home / "config.toml").read_text()) == tomllib.loads(original)

@pytest.mark.parametrize("arguments", [["reset", "--yes"], ["--reset", "--yes"]])
def test_reset_command_restores_defaults_and_keeps_user_data(
    home, monkeypatch, arguments
):
    original = (
        'model = "custom-model"\nmodel_provider = "p"\n'
        'model_catalog_json = "/custom.json"\n'
        'approval_policy = "never"\nmodel_reasoning_effort = "high"\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
        '[mcp_servers.example]\ncommand = "example"\n'
        '[projects."/work"]\ntrust_level = "trusted"\n'
    )
    config_path = home / "config.toml"
    config_path.write_text(original)
    (home / "models_cache.json").write_text('{"models": []}')
    (home / ".xsync-state.json").write_text("invalid old state")
    kept = {
        "auth.json": '{"token": "keep"}',
        "sessions/session.jsonl": "keep the session\n",
        "skills/example/SKILL.md": "keep the skill\n",
        "plugins/example/config.json": "{}",
        "p-models.json": '{"models": []}',
    }
    for name, content in kept.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setenv("XSYNC_PROFILES", str(home / "missing-profiles.toml"))

    assert cli.main(["codex", *arguments]) == 0

    assert tomllib.loads(config_path.read_text()) == {}
    backups = list(home.glob("config.toml.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert not (home / "models_cache.json").exists()
    assert not (home / ".xsync-state.json").exists()
    for name, content in kept.items():
        assert (home / name).read_text() == content

def test_reset_command_asks_before_it_resets_all_settings(home, monkeypatch, capsys):
    before = (home / "config.toml").read_text()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "no"

    monkeypatch.setattr("builtins.input", answer)

    assert cli.main(["codex", "reset"]) == 1
    assert "all" in prompts[0]
    assert "Caution:" in capsys.readouterr().out
    assert (home / "config.toml").read_text() == before
    assert not list(home.glob("config.toml.*.bak"))

def test_reset_command_dry_run_keeps_every_file_and_daemon(home, monkeypatch):
    before = (home / "config.toml").read_text()
    daemon_socket(home)
    (home / "models_cache.json").write_text("{}")

    def unexpected_run(*args, **kwargs):
        pytest.fail("A dry run must not stop the daemon.")

    monkeypatch.setattr(cli.subprocess, "run", unexpected_run)

    assert cli.main(["codex", "reset", "--dry-run"]) == 0
    assert (home / "config.toml").read_text() == before
    assert (home / "models_cache.json").exists()
    assert not list(home.glob("config.toml.*.bak"))

def test_reset_command_handles_a_broken_config_and_keeps_each_backup(home):
    (home / "config.toml").write_text("invalid = [")

    assert cli.main(["codex", "reset", "--yes"]) == 0
    assert (home / "config.toml").read_text() == ""
    assert cli.main(["codex", "reset", "--yes"]) == 0
    backups = list(home.glob("config.toml.*.bak"))
    assert len(backups) == 2
    assert {path.read_text() for path in backups} == {"invalid = [", ""}

def test_reset_command_targets_the_original_home_inside_an_xsync_session(
    home, monkeypatch
):
    monkeypatch.setenv("HOME", str(home.parent))
    real_home = home.parent / ".codex"
    real_home.mkdir()
    (real_home / "config.toml").write_text('model = "old"\n')
    isolated = home.parent / "homes" / "p" / "codex"
    isolated.mkdir(parents=True)
    isolated_config = isolated / "config.toml"
    isolated_config.write_text('model_provider = "p"\n')
    monkeypatch.setenv("CODEX_HOME", str(isolated))

    assert cli.main(["codex", "reset", "--yes"]) == 0
    assert (real_home / "config.toml").read_text() == ""
    assert isolated_config.read_text() == 'model_provider = "p"\n'

def test_reset_command_stops_the_daemon_before_it_resets_the_config(
    home, monkeypatch
):
    before = (home / "config.toml").read_text()
    daemon_socket(home)
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert (home / "config.toml").read_text() == before
        assert not list(home.glob("config.toml.*.bak"))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", run)

    assert cli.main(["codex", "reset", "--yes"]) == 0
    assert calls[0][0] == ["/bin/codex", "app-server", "daemon", "stop"]
    assert calls[0][1]["env"]["CODEX_HOME"] == str(home)
    assert (home / "config.toml").read_text() == ""

def test_reset_command_keeps_every_file_when_the_daemon_stop_fails(
    home, monkeypatch
):
    before = (home / "config.toml").read_text()
    daemon_socket(home)
    cache = home / "models_cache.json"
    cache.write_text("{}")
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1),
    )

    assert cli.main(["codex", "reset", "--yes"]) == 1
    assert (home / "config.toml").read_text() == before
    assert cache.exists()
    assert not list(home.glob("config.toml.*.bak"))

def test_reset_command_reports_the_daemon_error(home, monkeypatch, capsys):
    before = (home / "config.toml").read_text()
    daemon_socket(home)
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="Error: daemon refused to stop"
        ),
    )

    assert cli.main(["codex", "reset", "--yes"]) == 1
    assert "Error: daemon refused to stop" in capsys.readouterr().err
    assert (home / "config.toml").read_text() == before

def test_reset_command_reports_a_daemon_timeout(home, monkeypatch, capsys):
    daemon_socket(home)
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command, kwargs["timeout"], stderr=b"daemon shutdown pending"
        )

    monkeypatch.setattr(cli.subprocess, "run", timeout)

    assert cli.main(["codex", "reset", "--yes"]) == 1
    error = capsys.readouterr().err
    assert "15 seconds" in error
    assert "daemon shutdown pending" in error

def test_reset_flag_does_not_launch_codex_without_confirmation(
    home, monkeypatch
):
    before = (home / "config.toml").read_text()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)

    def unexpected_launch(*args, **kwargs):
        pytest.fail("--reset must not launch Codex.")

    monkeypatch.setattr(cli, "_open_harness", unexpected_launch)

    assert cli.main(["codex", "--reset"]) == 1
    assert (home / "config.toml").read_text() == before

def test_reset_command_keeps_every_file_when_the_backup_fails(home, monkeypatch):
    from xsync_cli.adapters import codex_wiring

    before = (home / "config.toml").read_text()
    cache = home / "models_cache.json"
    cache.write_text("{}")

    def fail_backup(*args, **kwargs):
        raise PermissionError("backup denied")

    monkeypatch.setattr(codex_wiring.os, "open", fail_backup)

    assert cli.main(["codex", "reset", "--yes"]) == 1
    assert (home / "config.toml").read_text() == before
    assert cache.exists()

def test_reset_command_keeps_a_concurrent_config_edit(home, monkeypatch):
    from xsync_cli.adapters import codex_wiring

    config_path = home / "config.toml"
    before = config_path.read_text()
    original_write = codex_wiring._atomic_toml_write
    concurrent = 'model = "concurrent-model"\n'

    def write_after_edit(path, document, digest):
        path.write_text(concurrent)
        return original_write(path, document, digest)

    monkeypatch.setattr(codex_wiring, "_atomic_toml_write", write_after_edit)

    assert cli.main(["codex", "reset", "--yes"]) == 1
    assert config_path.read_text() == concurrent
    backups = list(home.glob("config.toml.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == before

def test_reset_command_does_not_create_an_absent_config(home):
    (home / "config.toml").unlink()

    assert cli.main(["codex", "reset", "--yes"]) == 0
    assert not (home / "config.toml").exists()
    assert not list(home.glob("config.toml.*.bak"))

def test_reset_without_a_state_file_needs_force(home, capsys):
    assert cli.main(["codex", "apply", "--reset"]) == 1
    assert "--force" in capsys.readouterr().err


def daemon_socket(home):
    path = home / "app-server-control" / "app-server-control.sock"
    path.parent.mkdir()
    path.touch()
    return path

def test_apply_stops_the_daemon_before_it_writes_the_new_catalog(
    home, monkeypatch, capsys
):
    catalog_path = home / "p-models.json"
    catalog_path.write_text('{"models": [{"slug": "old"}]}')
    daemon_socket(home)
    calls = []
    monkeypatch.setattr(cli, "fetch_models", stub(["cx/gpt-6.1-sol"]))
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert json.loads(catalog_path.read_text())["models"][0]["slug"] == "old"
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", run)

    assert cli.main(["codex", "apply", "--yes"]) == 0

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == ["/bin/codex", "app-server", "daemon", "stop"]
    assert kwargs["env"]["CODEX_HOME"] == str(home)
    catalog = json.loads(catalog_path.read_text())
    assert [model["slug"] for model in catalog["models"]] == ["cx/gpt-6.1-sol"]
    assert "Restart" in capsys.readouterr().out

def test_apply_keeps_the_catalog_when_daemon_stop_fails(home, monkeypatch):
    catalog_path = home / "p-models.json"
    before_catalog = '{"models": [{"slug": "old"}]}'
    catalog_path.write_text(before_catalog)
    before_config = (home / "config.toml").read_text()
    daemon_socket(home)
    monkeypatch.setattr(cli, "fetch_models", stub(["cx/gpt-6.1-sol"]))
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="daemon stop failed"
        ),
    )

    assert cli.main(["codex", "apply", "--yes"]) == 1
    assert catalog_path.read_text() == before_catalog
    assert (home / "config.toml").read_text() == before_config
    assert not (home / ".xsync-state.json").exists()

def test_apply_dry_run_does_not_stop_the_daemon(home, monkeypatch):
    daemon_socket(home)
    monkeypatch.setattr(cli, "fetch_models", stub(["cx/gpt-6.1-sol"]))

    def unexpected_run(*args, **kwargs):
        pytest.fail("A dry run must not stop the daemon.")

    monkeypatch.setattr(cli.subprocess, "run", unexpected_run)

    assert cli.main(["codex", "apply", "--dry-run"]) == 0
    assert not (home / "p-models.json").exists()

def test_apply_updates_the_original_catalog_inside_an_xsync_session(
    home, monkeypatch
):
    monkeypatch.setenv("HOME", str(home.parent))
    real_home = home.parent / ".codex"
    real_home.mkdir()
    (real_home / "config.toml").write_text('model_reasoning_effort = "high"\n')
    isolated = home.parent / "homes" / "p" / "codex"
    isolated.mkdir(parents=True)
    isolated_catalog = isolated / "p-models.json"
    isolated_catalog.write_text('{"models": [{"slug": "old"}]}')
    monkeypatch.setenv("CODEX_HOME", str(isolated))
    monkeypatch.setattr(cli, "fetch_models", stub(["cx/gpt-6.1-sol"]))

    assert cli.main(["codex", "apply", "--yes"]) == 0

    catalog_path = real_home / "p-models.json"
    catalog = json.loads(catalog_path.read_text())
    assert [model["slug"] for model in catalog["models"]] == ["cx/gpt-6.1-sol"]
    config = tomllib.loads((real_home / "config.toml").read_text())
    assert config["model_catalog_json"] == str(catalog_path)
    assert config["model_reasoning_effort"] == "high"
    assert json.loads(isolated_catalog.read_text())["models"][0]["slug"] == "old"

def test_reset_stops_the_daemon_for_the_target_home(home, monkeypatch, capsys):
    (home / "config.toml").write_text('model_reasoning_effort = "high"\n')
    daemon_socket(home)
    cache = home / "models_cache.json"
    cache.write_text('{"models": []}')
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert cache.exists()
        assert "capture_output" not in kwargs
        assert kwargs["stdout"].fileno() >= 0
        assert kwargs["stderr"].fileno() >= 0
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", run)

    assert cli.main(["codex", "apply", "--reset", "--yes"]) == 0

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == ["/bin/codex", "app-server", "daemon", "stop"]
    assert kwargs["env"]["CODEX_HOME"] == str(home)
    assert kwargs["timeout"] > 0
    assert not cache.exists()
    assert "daemon" in capsys.readouterr().out

@pytest.mark.parametrize("failure", ["exit", "timeout", "os"])
def test_reset_keeps_everything_when_daemon_stop_fails(
    home, monkeypatch, capsys, failure
):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 0
    daemon_socket(home)
    before = (home / "config.toml").read_text()
    cache = home / "models_cache.json"
    cache.write_text('{"models": []}')
    monkeypatch.setattr(cli.shutil, "which", lambda command: "/bin/codex")
    def run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if failure == "os":
            raise OSError("daemon executable unavailable")
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="daemon stop failed"
        )

    monkeypatch.setattr(cli.subprocess, "run", run)

    assert cli.main(["codex", "apply", "--reset", "--yes"]) == 1

    assert (home / "config.toml").read_text() == before
    assert (home / ".xsync-state.json").exists()
    assert (home / "p-models.json").exists()
    assert cache.exists()
    assert "daemon" in capsys.readouterr().err

def test_reset_asks_before_it_disconnects_codex(home, monkeypatch):
    (home / "config.toml").write_text('model_reasoning_effort = "high"\n')
    daemon_socket(home)
    cache = home / "models_cache.json"
    cache.write_text('{"models": []}')
    asked = []
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)

    def answer(prompt):
        asked.append(prompt)
        return "no"

    def unexpected_run(*args, **kwargs):
        pytest.fail("Reset must not stop the daemon without confirmation.")

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(cli.subprocess, "run", unexpected_run)

    assert cli.main(["codex", "apply", "--reset"]) == 1
    assert asked
    assert "daemon" in asked[0]
    assert cache.exists()

def test_reset_removes_what_init_wrote(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "apply", "--init"])
    cli.main(["codex", "apply"])
    assert (home / "p-models.json").exists()

    assert cli.main(["codex", "apply", "--reset"]) == 0
    text = (home / "config.toml").read_text()
    assert "model_catalog_json" not in text
    assert not (home / "p-models.json").exists()
    assert not (home / ".xsync-state.json").exists()


def test_a_profile_override_uses_the_named_profile(home, monkeypatch):
    path = home.parent / "profiles.toml"
    path.write_text(
        'active = "p"\n\n[profiles.p]\n'
        'base_url = "http://h/v1"\nwire_api = "chat"\n'
        '\n[profiles.q]\nbase_url = "https://q/v1"\nwire_api = "chat"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--profile", "q", "--dry-run"]) == 0


def test_the_sync_output_names_the_profile_and_the_endpoint(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "apply", "--dry-run"])
    out = capsys.readouterr().out
    assert "p" in out
    assert "http://h/v1" in out


def test_the_sync_output_lists_added_models_on_their_own_lines(
    home, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "apply", "--dry-run"])
    lines = capsys.readouterr().out.splitlines()
    assert any(line.strip().endswith("a/one") for line in lines)
    assert any(line.strip().endswith("b/two") for line in lines)


def test_an_unchanged_sync_says_so(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "apply"])
    capsys.readouterr()
    cli.main(["codex", "apply", "--dry-run"])
    assert "up to date" in capsys.readouterr().out


def test_reset_force_asks_before_it_removes(home, monkeypatch, capsys):
    asked = {}

    def fake_input(prompt=""):
        asked["prompt"] = prompt
        return "no"

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)

    (home / "config.toml").write_text(
        'model_provider = "p"\nmodel_catalog_json = "/x.json"\n\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    cache = home / "models_cache.json"
    cache.write_text('{"models": []}')
    assert cli.main(["codex", "apply", "--reset", "--force"]) == 1
    assert "p" in asked["prompt"]
    assert "model_provider" in (home / "config.toml").read_text()
    assert cache.exists()


def test_reset_force_removes_after_a_yes(home, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)

    (home / "config.toml").write_text(
        'model_provider = "p"\nmodel_catalog_json = "/x.json"\n\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    assert cli.main(["codex", "apply", "--reset", "--force"]) == 0
    assert "model_provider" not in (home / "config.toml").read_text()


def test_reset_force_needs_no_answer_without_a_terminal(home, monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    (home / "config.toml").write_text(
        'model_provider = "p"\nmodel_catalog_json = "/x.json"\n\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    assert cli.main(["codex", "apply", "--reset", "--force", "--yes"]) == 0


def test_a_dry_run_writes_no_provider_block(home, monkeypatch):
    (home / "config.toml").write_text('model = "old"\n')
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--dry-run"]) == 0
    assert "model_providers" not in (home / "config.toml").read_text()
