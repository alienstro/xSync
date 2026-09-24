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
        return "sk-test-000000000000"

    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", fake_getpass)
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    assert cli.main(["setup"]) == 0
    assert "API key" in asked["prompt"]

    out = capsys.readouterr().out
    assert "sk-te…" in out
    assert "sk-test-000000000000" not in out


def test_setup_never_shows_the_key_length(store_path, monkeypatch, capsys):
    answers = iter(["p", "http://h/v1", "", "", "chat"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "sk-test-000000000000")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    cli.main(["setup"])
    out = capsys.readouterr().out
    assert "18" not in out
    assert "chars" not in out


def test_setup_does_not_ask_for_the_wire_api(
    store_path, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    prompts = []
    answers = iter(["p", "http://h/v1", "", ""])

    def answer(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(cli, "getpass", lambda prompt="": "")
    monkeypatch.setattr(cli, "fetch_models", fake_fetch(["a/one"]))

    assert cli.main(["setup"]) == 0
    assert not any("Wire API" in prompt for prompt in prompts)
    assert "Wire API" not in capsys.readouterr().out
    assert 'wire_api = "responses"' in store_path.read_text()


def test_the_help_command_shows_the_same_help(capsys):
    assert cli.main(["help"]) == 0
    out = capsys.readouterr().out
    for name in ("setup", "list", "use", "remove", "codex"):
        assert name in out
    assert "profiles.toml" in out


def test_the_help_command_can_explain_one_command(capsys):
    assert cli.main(["help", "codex"]) == 0
    out = capsys.readouterr().out
    assert "--dry-run" in out
    assert "--reset" in out


def test_the_help_of_an_unknown_command_fails(capsys):
    assert cli.main(["help", "nope"]) == 1
    assert "nope" in capsys.readouterr().err


def test_the_help_groups_the_commands(capsys):
    cli.main([])
    out = capsys.readouterr().out
    for group in ("PROFILES", "HARNESSES", "FILES"):
        assert group in out


def test_the_help_names_the_version(capsys):
    from importlib.metadata import version

    cli.main([])
    assert version("xsync-cli") in capsys.readouterr().out


def test_the_help_shows_every_command(capsys):
    cli.main([])
    out = capsys.readouterr().out
    for name in ("setup", "list", "use", "remove", "codex", "claude", "help"):
        assert name in out


def test_the_help_explains_apply(capsys):
    cli.main([])
    assert "apply" in capsys.readouterr().out


def test_the_help_holds_no_escape_code_in_a_pipe(capsys):
    cli.main([])
    assert "\x1b[" not in capsys.readouterr().out
