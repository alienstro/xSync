import stat

import pytest

from xsync_cli.core.profiles import Profile, ProfileError, ProfileStore


def sample(name="9router", **kw) -> Profile:
    base = dict(
        name=name,
        base_url="http://127.0.0.1:20128/v1",
        api_key="sk-secret",
        api_key_env=None,
        wire_api="responses",
        include=[],
        exclude=[],
    )
    base.update(kw)
    return Profile(**base)


def test_resolve_key_prefers_the_literal_key():
    assert sample().resolve_key({}) == "sk-secret"


def test_resolve_key_reads_the_named_variable():
    profile = sample(api_key=None, api_key_env="MY_KEY")
    assert profile.resolve_key({"MY_KEY": "sk-from-env"}) == "sk-from-env"


def test_resolve_key_raises_when_the_variable_is_absent():
    profile = sample(api_key=None, api_key_env="MY_KEY")
    with pytest.raises(ProfileError, match="MY_KEY"):
        profile.resolve_key({})


def test_resolve_key_returns_none_when_the_profile_has_no_key():
    profile = sample(api_key=None, api_key_env=None)
    assert profile.resolve_key({}) is None


def test_add_then_get_returns_the_same_profile(tmp_path):
    store = ProfileStore(tmp_path / "profiles.toml")
    store.load()
    store.add(sample())
    store.save()

    other = ProfileStore(tmp_path / "profiles.toml")
    other.load()
    assert other.get("9router").base_url == "http://127.0.0.1:20128/v1"
    assert other.get("9router").wire_api == "responses"


def test_the_first_profile_becomes_active(tmp_path):
    store = ProfileStore(tmp_path / "profiles.toml")
    store.load()
    store.add(sample())
    assert store.active == "9router"
    store.add(sample(name="second"))
    assert store.active == "9router"


def test_the_saved_file_is_user_readable_only(tmp_path):
    path = tmp_path / "profiles.toml"
    store = ProfileStore(path)
    store.load()
    store.add(sample())
    store.save()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_remove_clears_the_active_name(tmp_path):
    store = ProfileStore(tmp_path / "profiles.toml")
    store.load()
    store.add(sample())
    store.remove("9router")
    assert store.active is None
    assert store.names() == []


def test_remove_of_an_unknown_profile_raises(tmp_path):
    store = ProfileStore(tmp_path / "profiles.toml")
    store.load()
    with pytest.raises(ProfileError, match="unknown profile"):
        store.remove("absent")


def test_active_profile_raises_when_no_profile_exists(tmp_path):
    store = ProfileStore(tmp_path / "profiles.toml")
    store.load()
    with pytest.raises(ProfileError, match="no profile"):
        store.active_profile()


def test_a_profile_cannot_hold_both_key_forms():
    with pytest.raises(ProfileError, match="not both"):
        Profile(
            name="bad",
            base_url="http://x/v1",
            api_key="sk-1",
            api_key_env="MY_KEY",
            wire_api="chat",
            include=[],
            exclude=[],
        )


def test_the_base_url_loses_a_trailing_slash():
    assert sample(base_url="http://x/v1/").base_url == "http://x/v1"


def test_an_unknown_wire_api_raises():
    with pytest.raises(ProfileError, match="wire_api"):
        sample(wire_api="grpc")
