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
    assert cli.main(["codex", "apply"]) == 0
    catalog = json.loads((home / "p-models.json").read_text())
    assert [e["slug"] for e in catalog["models"]] == ["a/one", "b/two"]


def test_dry_run_writes_nothing(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--dry-run"]) == 0
    assert not (home / "p-models.json").exists()
    assert "no file written" in capsys.readouterr().out


def test_the_report_names_the_added_models(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "apply", "--dry-run"])
    assert "2 added" in capsys.readouterr().out


def test_a_second_sync_reports_the_difference(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "apply"])
    capsys.readouterr()
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "c/three"]))
    cli.main(["codex", "apply"])
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
    cli.main(["codex", "apply"])
    catalog = json.loads((home / "p-models.json").read_text())
    assert [e["slug"] for e in catalog["models"]] == ["a/one"]


def test_a_provider_mismatch_stops_the_write(home, monkeypatch, capsys):
    (home / "config.toml").write_text(
        'model_provider = "other"\n\n[model_providers.other]\n'
        'base_url = "https://other/v1"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply"]) == 1
    assert not (home / "p-models.json").exists()
    assert "--init" in capsys.readouterr().err


def test_a_mismatch_only_warns_on_a_dry_run(home, monkeypatch):
    (home / "config.toml").write_text(
        'model_provider = "other"\n\n[model_providers.other]\n'
        'base_url = "https://other/v1"\n'
    )
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--dry-run"]) == 0


def test_an_unreachable_endpoint_gives_exit_code_2(home, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    monkeypatch.setattr(cli, "fetch_models", failing)
    assert cli.main(["codex", "apply"]) == 2


def test_init_writes_the_provider_block(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--init"]) == 0
    text = (home / "config.toml").read_text()
    assert "[model_providers.p]" in text
    assert "model_catalog_json" in text
    assert (home / ".xsync-state.json").exists()


def test_reset_without_a_state_file_needs_force(home, capsys):
    assert cli.main(["codex", "apply", "--reset"]) == 1
    assert "--force" in capsys.readouterr().err


def test_reset_removes_what_init_wrote(home, monkeypatch):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "apply", "--init"])
    cli.main(["codex", "apply"])
    assert (home / "p-models.json").exists()

    assert cli.main(["codex", "apply", "--reset"]) == 0
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
    assert cli.main(["codex", "apply", "--profile", "q", "--dry-run"]) == 0


def test_the_sync_output_names_the_profile_and_the_endpoint(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "apply", "--dry-run"])
    out = capsys.readouterr().out
    assert "p" in out
    assert "http://h/v1" in out


def test_the_sync_output_lists_added_models_on_their_own_lines(
    home, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    cli.main(["codex", "apply", "--dry-run"])
    lines = capsys.readouterr().out.splitlines()
    assert any(line.strip().endswith("a/one") for line in lines)
    assert any(line.strip().endswith("b/two") for line in lines)


def test_an_unchanged_sync_says_so(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    cli.main(["codex", "apply"])
    capsys.readouterr()
    cli.main(["codex", "apply", "--dry-run"])
    assert "up to date" in capsys.readouterr().out


def test_reset_force_asks_before_it_removes(home, monkeypatch, capsys):
    asked = {}

    def fake_input(prompt=""):
        asked["prompt"] = prompt
        return "no"

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)

    (home / "config.toml").write_text(
        'model_provider = "p"\nmodel_catalog_json = "/x.json"\n\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    assert cli.main(["codex", "apply", "--reset", "--force"]) == 1
    assert "p" in asked["prompt"]
    assert "model_provider" in (home / "config.toml").read_text()


def test_reset_force_removes_after_a_yes(home, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)

    (home / "config.toml").write_text(
        'model_provider = "p"\nmodel_catalog_json = "/x.json"\n\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    assert cli.main(["codex", "apply", "--reset", "--force"]) == 0
    assert "model_provider" not in (home / "config.toml").read_text()


def test_reset_force_needs_no_answer_without_a_terminal(home, monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    (home / "config.toml").write_text(
        'model_provider = "p"\nmodel_catalog_json = "/x.json"\n\n'
        '[model_providers.p]\nbase_url = "http://h/v1"\n'
    )
    assert cli.main(["codex", "apply", "--reset", "--force", "--yes"]) == 0


def test_a_dry_run_writes_no_provider_block(home, monkeypatch):
    (home / "config.toml").write_text('model = "old"\n')
    monkeypatch.setattr(cli, "fetch_models", stub(["a/one"]))
    assert cli.main(["codex", "apply", "--dry-run"]) == 0
    assert "model_providers" not in (home / "config.toml").read_text()
