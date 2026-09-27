import json

import pytest

from xsync_cli import cli
from xsync_cli.core.install import Install


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "XDG_CONFIG_HOME",
        "PI_CODING_AGENT_DIR",
        "XSYNC_PROFILES",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def runs(monkeypatch):
    calls = []

    def run(command):
        calls.append(command)
        return 0

    monkeypatch.setattr(cli, "_run_command", run)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    return calls


def use_install(monkeypatch, install):
    monkeypatch.setattr(cli, "current_install", lambda prefix: install)


def test_update_pulls_and_reinstalls_a_checkout(home, runs, monkeypatch):
    source = home / "src"
    (source / ".git").mkdir(parents=True)
    use_install(monkeypatch, Install("uv", str(source), editable=True))
    monkeypatch.setattr(cli, "_command_output", lambda command: "")

    assert cli.main(["update"]) == 0
    assert runs == [
        ["git", "-C", str(source), "pull", "--ff-only"],
        ["uv", "tool", "install", "--force", "--reinstall", "--editable", str(source)],
    ]


def test_update_stops_on_uncommitted_changes(home, runs, monkeypatch, capsys):
    source = home / "src"
    (source / ".git").mkdir(parents=True)
    use_install(monkeypatch, Install("uv", str(source), editable=True))
    monkeypatch.setattr(cli, "_command_output", lambda command: " M cli.py\n")

    assert cli.main(["update"]) == 1
    assert runs == []
    assert "uncommitted" in capsys.readouterr().err


def test_update_dry_run_runs_nothing(home, runs, monkeypatch, capsys):
    use_install(monkeypatch, Install("uv", None, editable=False))
    assert cli.main(["update", "--dry-run"]) == 0
    assert runs == []
    assert "uv tool upgrade xsync-cli" in capsys.readouterr().out


def test_update_stops_when_a_tool_is_missing(home, runs, monkeypatch, capsys):
    use_install(monkeypatch, Install("pipx", None, editable=False))
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.main(["update"]) == 1
    assert runs == []
    assert "pipx" in capsys.readouterr().err


def test_update_stops_after_a_failed_step(home, monkeypatch):
    source = home / "src"
    (source / ".git").mkdir(parents=True)
    use_install(monkeypatch, Install("uv", str(source), editable=True))
    monkeypatch.setattr(cli, "_command_output", lambda command: "")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    calls = []

    def failing(command):
        calls.append(command)
        return 1

    monkeypatch.setattr(cli, "_run_command", failing)
    assert cli.main(["update"]) == 1
    assert len(calls) == 1


def write_codex_state(home):
    codex = home / ".codex"
    codex.mkdir()
    catalog = codex / "p-models.json"
    catalog.write_text("{}")
    (codex / "config.toml").write_text(
        f'model_catalog_json = "{catalog}"\nmodel_provider = "p"\n'
    )
    (codex / ".xsync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "codex": {
                    "profile": "p",
                    "keys_written": ["model_catalog_json", "model_provider"],
                    "files_written": [str(catalog)],
                },
            }
        )
    )
    return codex


def write_profiles(home):
    folder = home / ".config" / "xsync"
    (folder / "homes" / "p").mkdir(parents=True)
    (folder / "profiles.toml").write_text('[profiles.p]\nbase_url = "http://h/v1"\n')
    return folder


def test_uninstall_resets_the_harness_then_removes_the_package(
    home, runs, monkeypatch
):
    codex = write_codex_state(home)
    folder = write_profiles(home)
    use_install(monkeypatch, Install("uv", None, editable=False))

    assert cli.main(["uninstall", "--yes"]) == 0
    assert "model_provider" not in (codex / "config.toml").read_text()
    assert not (codex / ".xsync-state.json").exists()
    assert (folder / "profiles.toml").exists()
    assert runs == [["uv", "tool", "uninstall", "xsync-cli"]]


def test_uninstall_purge_deletes_the_profiles(home, runs, monkeypatch):
    folder = write_profiles(home)
    use_install(monkeypatch, Install("uv", None, editable=False))

    assert cli.main(["uninstall", "--yes", "--purge"]) == 0
    assert not folder.exists()


def test_uninstall_dry_run_changes_nothing(home, runs, monkeypatch, capsys):
    codex = write_codex_state(home)
    use_install(monkeypatch, Install("uv", None, editable=False))

    assert cli.main(["uninstall", "--dry-run"]) == 0
    assert (codex / ".xsync-state.json").exists()
    assert runs == []
    assert "codex" in capsys.readouterr().out.lower()


def test_uninstall_without_a_yes_stops(home, runs, monkeypatch):
    codex = write_codex_state(home)
    use_install(monkeypatch, Install("uv", None, editable=False))

    # A test has no terminal, so the question gives no.
    assert cli.main(["uninstall"]) == 1
    assert (codex / ".xsync-state.json").exists()
    assert runs == []
