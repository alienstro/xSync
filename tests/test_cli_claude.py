import json

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
    claude = tmp_path / "claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"model": "opus", "env": {"ANTHROPIC_BASE_URL": "http://h/v1"}})
    )
    monkeypatch.setenv("XSYNC_PROFILES", str(profiles))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    return claude


def stub(slugs):
    def fetch(base_url, api_key, timeout=10.0, retries=2, opener=None):
        return parse_models({"data": [{"id": s} for s in slugs]})

    return fetch


def settings(home) -> dict:
    return json.loads((home / "settings.json").read_text())


def test_sync_writes_the_picker_rows(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    assert cli.main(["claude", "apply"]) == 0
    rows = settings(home)["modelPicker"]["options"]
    assert [r["model"] for r in rows] == ["a/one", "b/two"]


def test_the_built_in_models_stay(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["claude", "apply"])
    assert settings(home)["modelPicker"]["replaceBuiltInOptions"] is False


def test_an_unknown_model_gets_a_map(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["cmc/deepseek/deepseek-v4-pro"]))
    cli.main(["claude", "apply"])
    assert settings(home)["modelPicker"]["options"][0]["behavesAs"] == "claude-opus-4-8"


def test_a_claude_model_keeps_its_native_handling(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["ed3n/claude-sonnet-5"]))
    cli.main(["claude", "apply"])
    assert "behavesAs" not in settings(home)["modelPicker"]["options"][0]


def test_dry_run_writes_nothing(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["claude", "apply", "--dry-run"]) == 0
    assert "modelPicker" not in settings(home)
    assert "no file written" in capsys.readouterr().out


def test_the_settings_keep_every_other_key(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["claude", "apply"])
    assert settings(home)["model"] == "opus"


def test_a_dry_run_warns_about_a_different_endpoint(home, monkeypatch, capsys):
    """`apply` rewires the endpoint, so only a dry run can disagree."""
    (home / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://other"}})
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["claude", "apply", "--dry-run"]) == 0
    assert "https://other" in capsys.readouterr().out
    assert "modelPicker" not in settings(home)


def test_a_dry_run_writes_no_endpoint(home, monkeypatch):
    (home / "settings.json").write_text(json.dumps({"model": "opus"}))
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["claude", "apply", "--dry-run"]) == 0
    assert "env" not in settings(home)


def test_init_writes_the_endpoint(home, monkeypatch):
    (home / "settings.json").write_text(json.dumps({"model": "opus"}))
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["claude", "apply", "--init"]) == 0
    data = settings(home)
    assert data["env"]["ANTHROPIC_BASE_URL"] == "http://h/v1"
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-1"
    assert (home / ".xsync-state.json").exists()


def test_an_unreachable_endpoint_gives_exit_code_2(home, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    monkeypatch.setattr(cli, "fetch_models", failing)
    assert cli.main(["claude", "apply"]) == 2


def test_reset_removes_what_xsync_wrote(home, monkeypatch):
    (home / "settings.json").write_text(json.dumps({"model": "opus"}))
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["claude", "apply", "--init"])
    assert "modelPicker" in settings(home)

    assert cli.main(["claude", "apply", "--reset"]) == 0
    data = settings(home)
    assert "modelPicker" not in data
    assert "ANTHROPIC_BASE_URL" not in data.get("env", {})
    assert data["model"] == "opus"
    assert not (home / ".xsync-state.json").exists()


def test_reset_without_a_state_file_needs_force(home, capsys):
    assert cli.main(["claude", "apply", "--reset"]) == 1
    assert "--force" in capsys.readouterr().err


def test_the_exclude_rule_drops_a_model(home, monkeypatch):
    (home.parent / "profiles.toml").write_text(
        'active = "p"\n\n[profiles.p]\n'
        'base_url = "http://h/v1"\nwire_api = "chat"\nexclude = ["*embedding*"]\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "a/text-embedding-3"]))
    cli.main(["claude", "apply"])
    rows = settings(home)["modelPicker"]["options"]
    assert [r["model"] for r in rows] == ["a/one"]
