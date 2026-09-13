import json

import pytest

from xsync_cli.adapters.claude_config import (
    STATE_FILENAME,
    ClaudeConfigError,
    base_url_of,
    check_endpoint_match,
    default_claude_home,
    init_settings,
    read_settings,
    reset_settings,
    settings_path_for,
)
from xsync_cli.core.profiles import Profile


def profile(name="9router", base_url="http://127.0.0.1:20128") -> Profile:
    return Profile(
        name=name,
        base_url=base_url,
        api_key="sk-1",
        api_key_env=None,
        wire_api="responses",
        include=[],
        exclude=[],
    )


EXISTING = {
    "model": "opus[1m]",
    "env": {"NODE_OPTIONS": "--max-old-space-size=512"},
    "hooks": {"PermissionRequest": [{"matcher": "*"}]},
    "statusLine": {"type": "command"},
}


def write_settings(tmp_path, data=None):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data if data is not None else EXISTING, indent=2))
    return path


def test_the_home_follows_the_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert default_claude_home() == tmp_path


def test_the_settings_path_sits_in_the_home(tmp_path):
    assert settings_path_for(tmp_path).name == "settings.json"


def test_reading_an_absent_file_gives_an_empty_mapping(tmp_path):
    assert read_settings(tmp_path / "absent.json") == {}


def test_reading_a_damaged_file_raises(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    with pytest.raises(ClaudeConfigError, match="JSON"):
        read_settings(path)


def test_the_base_url_comes_from_the_env_block():
    settings = {"env": {"ANTHROPIC_BASE_URL": "http://h/"}}
    assert base_url_of(settings) == "http://h"


def test_an_absent_base_url_is_none():
    assert base_url_of({}) is None


def test_a_matching_endpoint_gives_no_message():
    settings = {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:20128"}}
    assert check_endpoint_match(settings, profile()) is None


def test_a_different_endpoint_gives_a_message():
    settings = {"env": {"ANTHROPIC_BASE_URL": "https://other"}}
    message = check_endpoint_match(settings, profile())
    assert "--init" in message


def test_no_endpoint_gives_a_message():
    assert "--init" in check_endpoint_match({}, profile())


def test_init_writes_the_endpoint_and_keeps_everything_else(tmp_path):
    path = write_settings(tmp_path)
    init_settings(path, profile(), "sk-1")

    data = json.loads(path.read_text())
    assert data["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:20128"
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-1"
    assert data["env"]["NODE_OPTIONS"] == "--max-old-space-size=512"
    assert data["model"] == "opus[1m]"
    assert data["hooks"] == EXISTING["hooks"]
    assert data["statusLine"] == EXISTING["statusLine"]


def test_init_without_a_key_writes_no_token(tmp_path):
    path = write_settings(tmp_path)
    init_settings(path, profile(), None)
    assert "ANTHROPIC_AUTH_TOKEN" not in json.loads(path.read_text())["env"]


def test_init_records_the_state(tmp_path):
    path = write_settings(tmp_path)
    state = init_settings(path, profile(), "sk-1")
    assert state.profile == "9router"
    assert "env.ANTHROPIC_BASE_URL" in state.keys_written
    assert state.settings_sha256


def test_init_keeps_a_backup(tmp_path):
    path = write_settings(tmp_path)
    init_settings(path, profile(), "sk-1")
    assert (tmp_path / "settings.json.bak").exists()


def test_reset_removes_only_what_init_wrote(tmp_path):
    path = write_settings(tmp_path)
    state = init_settings(path, profile(), "sk-1")
    reset_settings(path, state)

    data = json.loads(path.read_text())
    assert "ANTHROPIC_BASE_URL" not in data.get("env", {})
    assert "ANTHROPIC_AUTH_TOKEN" not in data.get("env", {})
    assert data["env"]["NODE_OPTIONS"] == "--max-old-space-size=512"
    assert data["model"] == "opus[1m]"
    assert data["hooks"] == EXISTING["hooks"]


def test_write_picker_adds_the_rows_after_the_built_ins(tmp_path):
    from xsync_cli.adapters.claude_config import write_picker

    path = write_settings(tmp_path)
    write_picker(path, [{"model": "a/b", "label": "A B"}])

    picker = json.loads(path.read_text())["modelPicker"]
    assert picker["options"] == [{"model": "a/b", "label": "A B"}]
    assert picker["replaceBuiltInOptions"] is False


def test_write_picker_keeps_the_rest_of_the_file(tmp_path):
    from xsync_cli.adapters.claude_config import write_picker

    path = write_settings(tmp_path)
    write_picker(path, [{"model": "a/b"}])
    data = json.loads(path.read_text())
    assert data["hooks"] == EXISTING["hooks"]
    assert data["model"] == "opus[1m]"


def test_reset_removes_the_picker_rows(tmp_path):
    import dataclasses

    from xsync_cli.adapters.claude_config import write_picker

    path = write_settings(tmp_path)
    state = init_settings(path, profile(), "sk-1")
    write_picker(path, [{"model": "a/b"}])
    state = dataclasses.replace(
        state, keys_written=[*state.keys_written, "modelPicker"]
    )

    reset_settings(path, state)
    assert "modelPicker" not in json.loads(path.read_text())


def test_the_hash_guard_stops_a_concurrent_edit(tmp_path, monkeypatch):
    path = write_settings(tmp_path)
    from xsync_cli.adapters import claude_config

    original = claude_config.file_sha256
    calls = {"n": 0}

    def changing(target):
        calls["n"] += 1
        if calls["n"] >= 2:
            path.write_text(json.dumps({**EXISTING, "extra": 1}))
        return original(target)

    monkeypatch.setattr(claude_config, "file_sha256", changing)
    with pytest.raises(ClaudeConfigError, match="changed during"):
        init_settings(path, profile(), "sk-1")


def test_the_state_file_name():
    assert STATE_FILENAME == ".xsync-state.json"
