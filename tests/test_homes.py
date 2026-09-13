import os

import pytest

from xsync_cli.core.homes import (
    SHARED_CLAUDE,
    SHARED_CODEX,
    HomeError,
    home_for,
    homes_root,
    launch,
    link_shared,
)


def test_the_root_sits_next_to_the_profiles(monkeypatch, tmp_path):
    monkeypatch.setenv("XSYNC_PROFILES", str(tmp_path / "profiles.toml"))
    assert homes_root() == tmp_path / "homes"


def test_one_home_for_each_profile_and_harness(monkeypatch, tmp_path):
    monkeypatch.setenv("XSYNC_PROFILES", str(tmp_path / "profiles.toml"))
    assert home_for("9router", "codex") == tmp_path / "homes" / "9router" / "codex"
    assert home_for("9router", "claude") == tmp_path / "homes" / "9router" / "claude"


def test_a_profile_name_with_a_slash_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("XSYNC_PROFILES", str(tmp_path / "profiles.toml"))
    with pytest.raises(HomeError, match="name"):
        home_for("../escape", "codex")


def test_link_shared_makes_a_symlink(tmp_path):
    source = tmp_path / "real"
    (source / "skills").mkdir(parents=True)
    (source / "skills" / "a.md").write_text("hi")
    target = tmp_path / "iso"
    target.mkdir()

    linked = link_shared(source, target, ("skills",))

    assert linked == ["skills"]
    assert (target / "skills").is_symlink()
    assert (target / "skills" / "a.md").read_text() == "hi"


def test_link_shared_skips_a_missing_name(tmp_path):
    source = tmp_path / "real"
    source.mkdir()
    target = tmp_path / "iso"
    target.mkdir()
    assert link_shared(source, target, ("absent",)) == []


def test_link_shared_leaves_a_real_directory_alone(tmp_path):
    source = tmp_path / "real"
    (source / "skills").mkdir(parents=True)
    target = tmp_path / "iso"
    (target / "skills").mkdir(parents=True)
    (target / "skills" / "mine.md").write_text("keep")

    link_shared(source, target, ("skills",))

    assert not (target / "skills").is_symlink()
    assert (target / "skills" / "mine.md").read_text() == "keep"


def test_link_shared_repoints_its_own_stale_link(tmp_path):
    source = tmp_path / "real"
    (source / "skills").mkdir(parents=True)
    other = tmp_path / "old"
    other.mkdir()
    target = tmp_path / "iso"
    target.mkdir()
    (target / "skills").symlink_to(other)

    link_shared(source, target, ("skills",))

    assert (target / "skills").resolve() == source.joinpath("skills").resolve()


def test_link_shared_copies_a_file(tmp_path):
    source = tmp_path / "real"
    source.mkdir()
    (source / "CLAUDE.md").write_text("rules")
    target = tmp_path / "iso"
    target.mkdir()

    assert link_shared(source, target, ("CLAUDE.md",)) == ["CLAUDE.md"]
    assert (target / "CLAUDE.md").read_text() == "rules"


def test_launch_runs_the_command_with_the_home_variable():
    seen = {}

    def fake_exec(command, argv, env):
        seen["command"] = command
        seen["argv"] = argv
        seen["env"] = env

    launch("claude", "CLAUDE_CONFIG_DIR", "/tmp/home", ["--model", "x"], exec_fn=fake_exec)

    assert seen["command"] == "claude"
    assert seen["argv"] == ["claude", "--model", "x"]
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == "/tmp/home"


def test_launch_keeps_the_rest_of_the_environment():
    seen = {}
    os.environ["XSYNC_TEST_MARKER"] = "1"

    def fake_exec(command, argv, env):
        seen["env"] = env

    launch("codex", "CODEX_HOME", "/tmp/h", [], exec_fn=fake_exec)
    assert seen["env"]["XSYNC_TEST_MARKER"] == "1"
    del os.environ["XSYNC_TEST_MARKER"]


def test_launch_reports_a_missing_command():
    def fake_exec(command, argv, env):
        raise FileNotFoundError(command)

    with pytest.raises(HomeError, match="not found"):
        launch("nope", "X", "/tmp/h", [], exec_fn=fake_exec)


def test_the_shared_names_hold_no_session_state():
    for name in SHARED_CODEX + SHARED_CLAUDE:
        assert "session" not in name
        assert name not in ("cache", "logs", "log", "projects", "telemetry")
