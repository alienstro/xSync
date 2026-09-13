import pytest

from xsync_cli.adapters.codex_config import (
    State,
    active_provider,
    catalog_path_for,
    check_provider_match,
    clear_state,
    file_sha256,
    read_state,
    write_state,
)
from xsync_cli.core.profiles import Profile


def profile(name="9router", base_url="http://127.0.0.1:20128/v1") -> Profile:
    return Profile(
        name=name,
        base_url=base_url,
        api_key="sk-1",
        api_key_env=None,
        wire_api="responses",
        include=[],
        exclude=[],
    )


CONFIG = {
    "model_provider": "9router",
    "model_providers": {
        "9router": {"name": "9Router", "base_url": "http://127.0.0.1:20128/v1"},
        "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
    },
}


def test_active_provider_reads_the_name_and_the_url():
    assert active_provider(CONFIG) == ("9router", "http://127.0.0.1:20128/v1")


def test_active_provider_is_none_without_a_provider_key():
    assert active_provider({}) is None


def test_a_matching_profile_gives_no_message():
    assert check_provider_match(CONFIG, profile()) is None


def test_a_different_url_gives_a_message():
    message = check_provider_match(CONFIG, profile("openrouter", "https://other/v1"))
    assert "openrouter" in message
    assert "--init" in message


def test_a_trailing_slash_still_matches():
    config = {
        "model_provider": "p",
        "model_providers": {"p": {"base_url": "http://127.0.0.1:20128/v1/"}},
    }
    assert check_provider_match(config, profile()) is None


def test_an_absent_provider_gives_a_message():
    assert "--init" in check_provider_match({}, profile())


def test_the_catalog_path_uses_the_profile_name(tmp_path):
    assert catalog_path_for(profile(), tmp_path).name == "9router-models.json"


def test_the_state_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = State(
        profile="9router",
        keys_written=["model_provider"],
        blocks_written=["model_providers.9router"],
        files_written=["/tmp/catalog.json"],
        config_sha256="abc",
        written_at="2026-09-13T00:00:00Z",
    )
    write_state(path, state)
    assert read_state(path) == state


def test_reading_an_absent_state_gives_none(tmp_path):
    assert read_state(tmp_path / "absent.json") is None


def test_clear_state_deletes_the_file(tmp_path):
    path = tmp_path / "state.json"
    write_state(
        path,
        State("p", [], [], [], "abc", "2026-09-13T00:00:00Z"),
    )
    clear_state(path)
    assert not path.exists()


def test_the_hash_changes_with_the_content(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("a = 1")
    first = file_sha256(path)
    path.write_text("a = 2")
    assert file_sha256(path) != first
