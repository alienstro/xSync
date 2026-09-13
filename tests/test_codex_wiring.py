import tomllib

import pytest

from xsync_cli.adapters.codex_config import ConfigError
from xsync_cli.adapters.codex_wiring import init_config, known_removals, reset_config
from xsync_cli.core.profiles import Profile


def profile(name="9router") -> Profile:
    return Profile(
        name=name,
        base_url="http://127.0.0.1:20128/v1",
        api_key="sk-1",
        api_key_env=None,
        wire_api="responses",
        include=[],
        exclude=[],
    )


EXISTING = """\
model_reasoning_effort = "max"

[projects."/Users/x/one"]
trust_level = "trusted"

[projects."/Users/x/two"]
trust_level = "trusted"
"""


def test_init_adds_the_provider_block(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)
    init_config(config, profile(), tmp_path / "9router-models.json", "sk-1")

    data = tomllib.loads(config.read_text())
    assert data["model_provider"] == "9router"
    assert data["model_providers"]["9router"]["base_url"] == "http://127.0.0.1:20128/v1"
    assert data["model_providers"]["9router"]["wire_api"] == "responses"
    assert (
        data["model_providers"]["9router"]["http_headers"]["Authorization"]
        == "Bearer sk-1"
    )
    assert data["model_catalog_json"].endswith("9router-models.json")


def test_init_keeps_every_project_entry(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)
    init_config(config, profile(), tmp_path / "c.json", "sk-1")

    data = tomllib.loads(config.read_text())
    assert set(data["projects"]) == {"/Users/x/one", "/Users/x/two"}
    assert data["model_reasoning_effort"] == "max"


def test_init_writes_no_header_without_a_key(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)
    init_config(config, profile(), tmp_path / "c.json", None)

    data = tomllib.loads(config.read_text())
    assert "http_headers" not in data["model_providers"]["9router"]


def test_init_records_the_state(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)
    state = init_config(config, profile(), tmp_path / "c.json", "sk-1")

    assert state.profile == "9router"
    assert "model_catalog_json" in state.keys_written
    assert "model_providers.9router" in state.blocks_written
    assert state.config_sha256


def test_init_does_not_record_a_key_it_did_not_write(tmp_path):
    config = tmp_path / "config.toml"
    # The key must stay at the top level. A key after a table belongs to
    # that table.
    config.write_text('model_provider = "other"\n' + EXISTING)
    state = init_config(config, profile(), tmp_path / "c.json", "sk-1")
    assert "model_provider" not in state.keys_written
    assert tomllib.loads(config.read_text())["model_provider"] == "other"


def test_reset_removes_only_the_recorded_items(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)
    catalog = tmp_path / "c.json"
    catalog.write_text("{}")
    state = init_config(config, profile(), catalog, "sk-1")

    reset_config(config, state)

    data = tomllib.loads(config.read_text())
    assert "model_catalog_json" not in data
    assert "9router" not in data.get("model_providers", {})
    assert set(data["projects"]) == {"/Users/x/one", "/Users/x/two"}
    assert data["model_reasoning_effort"] == "max"


def test_reset_deletes_the_catalog_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)
    catalog = tmp_path / "c.json"
    catalog.write_text("{}")
    backup = tmp_path / "c.json.bak"
    backup.write_text("{}")
    state = init_config(config, profile(), catalog, "sk-1")

    reset_config(config, state)
    assert not catalog.exists()
    assert not backup.exists()


def test_the_hash_guard_stops_a_concurrent_edit(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(EXISTING)

    from xsync_cli.adapters import codex_wiring

    original = codex_wiring.file_sha256
    calls = {"n": 0}

    def changing(path):
        calls["n"] += 1
        if calls["n"] >= 2:
            config.write_text(EXISTING + "\nextra = 1\n")
        return original(path)

    monkeypatch.setattr(codex_wiring, "file_sha256", changing)

    with pytest.raises(ConfigError, match="changed during"):
        init_config(config, profile(), tmp_path / "c.json", "sk-1")


def test_known_removals_names_the_standard_keys():
    state = known_removals("9router")
    assert "model_catalog_json" in state.keys_written
    assert "model_providers.9router" in state.blocks_written
