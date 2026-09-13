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
    assert cli.main(["codex"]) == 0
    catalog = json.loads((home / "p-models.json").read_text())
    assert [e["slug"] for e in catalog["models"]] == ["a/one", "b/two"]


def test_dry_run_writes_nothing(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "--dry-run"]) == 0
    assert not (home / "p-models.json").exists()
    assert "no files written" in capsys.readouterr().out


def test_the_report_names_the_added_models(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "--dry-run"])
    assert "2 added" in capsys.readouterr().out


def test_a_second_sync_reports_the_difference(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex"])
    capsys.readouterr()
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "c/three"]))
    cli.main(["codex"])
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
    cli.main(["codex"])
    catalog = json.loads((home / "p-models.json").read_text())
    assert [e["slug"] for e in catalog["models"]] == ["a/one"]


def test_a_provider_mismatch_stops_the_write(home, monkeypatch, capsys):
    (home / "config.toml").write_text(
        'model_provider = "other"\n\n[model_providers.other]\n'
        'base_url = "https://other/v1"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex"]) == 1
    assert not (home / "p-models.json").exists()
    assert "--init" in capsys.readouterr().err


def test_a_mismatch_only_warns_on_a_dry_run(home, monkeypatch):
    (home / "config.toml").write_text(
        'model_provider = "other"\n\n[model_providers.other]\n'
        'base_url = "https://other/v1"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "--dry-run"]) == 0


def test_an_unreachable_endpoint_gives_exit_code_2(home, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    monkeypatch.setattr(cli, "fetch_models", failing)
    assert cli.main(["codex"]) == 2


def test_init_writes_the_provider_block(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "--init"]) == 0
    text = (home / "config.toml").read_text()
    assert "[model_providers.p]" in text
    assert "model_catalog_json" in text
    assert (home / ".xsync-state.json").exists()


def test_reset_without_a_state_file_needs_force(home, capsys):
    assert cli.main(["codex", "--reset"]) == 1
    assert "--force" in capsys.readouterr().err


def test_reset_removes_what_init_wrote(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "--init"])
    cli.main(["codex"])
    assert (home / "p-models.json").exists()

    assert cli.main(["codex", "--reset"]) == 0
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
    assert cli.main(["codex", "--profile", "q", "--dry-run"]) == 0
