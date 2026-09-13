import pytest

from xsync_cli import cli


@pytest.fixture
def store_path(tmp_path, monkeypatch):
    path = tmp_path / "profiles.toml"
    monkeypatch.setenv("XSYNC_PROFILES", str(path))
    return path


def fake_fetch(models):
    def fetch(base_url, api_key, timeout=10.0, retries=2, opener=None):
        from xsync_cli.sources.openai_compat import parse_models

        return parse_models({"data": [{"id": slug} for slug in models]})

    return fetch


def test_setup_writes_a_profile(store_path, monkeypatch, capsys):
    answers = iter(["9router", "http://127.0.0.1:20128/v1", "", "", "responses"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "sk-1")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one", "b/two"]))

    assert cli.main(["setup"]) == 0
    text = store_path.read_text()
    assert 'base_url = "http://127.0.0.1:20128/v1"' in text
    assert 'active = "9router"' in text


def test_setup_prints_the_models(store_path, monkeypatch, capsys):
    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one", "b/two"]))

    cli.main(["setup"])
    out = capsys.readouterr().out
    assert "a/one" in out
    assert "b/two" in out
    assert "2 models" in out


def test_setup_never_prints_the_key(store_path, monkeypatch, capsys):
    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "sk-secret-value")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    cli.main(["setup"])
    assert "sk-secret-value" not in capsys.readouterr().out


def test_setup_stops_when_the_endpoint_fails(store_path, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "")

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    monkeypatch.setattr(cli, "fetch_models", failing)

    assert cli.main(["setup"]) == 2
    assert not store_path.exists()


def test_list_marks_the_active_profile(store_path, capsys):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        'active = "a"\n\n[profiles.a]\nbase_url = "http://a/v1"\nwire_api = "chat"\n'
        '\n[profiles.b]\nbase_url = "http://b/v1"\nwire_api = "chat"\n'
    )
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "a" in out and "b" in out
    assert "(active)" in out
    assert "http://a/v1" in out


def test_use_switches_the_active_profile(store_path):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        'active = "a"\n\n[profiles.a]\nbase_url = "http://a/v1"\nwire_api = "chat"\n'
        '\n[profiles.b]\nbase_url = "http://b/v1"\nwire_api = "chat"\n'
    )
    assert cli.main(["use", "b"]) == 0
    assert 'active = "b"' in store_path.read_text()


def test_use_of_an_unknown_profile_fails(store_path, capsys):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text('[profiles.a]\nbase_url = "http://a/v1"\nwire_api = "chat"\n')
    assert cli.main(["use", "absent"]) == 1
    assert "unknown profile" in capsys.readouterr().err


def test_remove_deletes_the_profile(store_path):
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text('[profiles.a]\nbase_url = "http://a/v1"\nwire_api = "chat"\n')
    assert cli.main(["remove", "a"]) == 0
    assert "profiles.a" not in store_path.read_text()


def test_a_bare_command_shows_the_help(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    for name in ("setup", "list", "use", "remove", "codex"):
        assert name in out


def test_the_help_names_the_profile_file(capsys):
    cli.main([])
    assert "profiles.toml" in capsys.readouterr().out


def test_the_help_shows_an_example(capsys):
    cli.main([])
    assert "xsync setup" in capsys.readouterr().out


def test_setup_hides_the_key_while_the_user_types(store_path, monkeypatch, capsys):
    asked = {}

    def fake_getpass(prompt=""):
        asked["prompt"] = prompt
        return "sk-92465eb0c2f2e2d5"

    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", fake_getpass)
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    assert cli.main(["setup"]) == 0
    assert "API key" in asked["prompt"]

    out = capsys.readouterr().out
    assert "sk-92…" in out
    assert "sk-92465eb0c2f2e2d5" not in out


def test_setup_never_shows_the_key_length(store_path, monkeypatch, capsys):
    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "sk-92465eb0c2f2e2d5")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    cli.main(["setup"])
    out = capsys.readouterr().out
    assert "18" not in out
    assert "chars" not in out


def test_setup_takes_the_wire_api_from_an_existing_provider(
    store_path, tmp_path, monkeypatch, capsys
):
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        '[model_providers.old]\n'
        'base_url = "http://h/v1"\nwire_api = "responses"\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(codex))

    answers = iter(["p", "http://h/v1", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    assert cli.main(["setup"]) == 0
    assert 'wire_api = "responses"' in store_path.read_text()
