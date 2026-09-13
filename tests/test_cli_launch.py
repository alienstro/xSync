import json

import pytest

from xsync_cli import cli
from xsync_cli.sources.openai_compat import parse_models


@pytest.fixture
def env(tmp_path, monkeypatch):
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(
        'active = "p"\n\n[profiles.p]\n'
        'base_url = "http://h/v1"\nwire_api = "chat"\napi_key = "sk-1"\n'
    )
    monkeypatch.setenv("XSYNC_PROFILES", str(profiles))

    codex = tmp_path / "real-codex"
    codex.mkdir()
    (codex / "config.toml").write_text('model = "old"\n')
    monkeypatch.setenv("CODEX_HOME", str(codex))

    claude = tmp_path / "real-claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"model": "opus"}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))

    monkeypatch.setattr(cli, "fetch_models", stub(["a/one", "b/two"]))
    return tmp_path


def stub(slugs):
    def fetch(base_url, api_key, timeout=10.0, retries=2, opener=None):
        return parse_models({"data": [{"id": s} for s in slugs]})

    return fetch


@pytest.fixture
def spy(monkeypatch):
    calls = {}

    def fake_launch(command, home_variable, home, extra_args, exec_fn=None):
        calls["command"] = command
        calls["variable"] = home_variable
        calls["home"] = str(home)
        calls["args"] = list(extra_args)

    monkeypatch.setattr(cli, "launch", fake_launch)
    return calls


def test_codex_launches_an_isolated_instance(env, spy):
    assert cli.main(["codex"]) == 0
    assert spy["command"] == "codex"
    assert spy["variable"] == "CODEX_HOME"
    assert spy["home"].endswith("homes/p/codex")


def test_claude_launches_an_isolated_instance(env, spy):
    assert cli.main(["claude"]) == 0
    assert spy["command"] == "claude"
    assert spy["variable"] == "CLAUDE_CONFIG_DIR"
    assert spy["home"].endswith("homes/p/claude")


def test_the_isolated_codex_home_holds_the_catalog(env, spy):
    cli.main(["codex"])
    catalog = json.loads(
        (env / "homes" / "p" / "codex" / "p-models.json").read_text()
    )
    assert [m["slug"] for m in catalog["models"]] == ["a/one", "b/two"]


def test_the_isolated_claude_home_holds_the_rows(env, spy):
    cli.main(["claude"])
    data = json.loads((env / "homes" / "p" / "claude" / "settings.json").read_text())
    assert len(data["modelPicker"]["options"]) == 2


def test_a_launch_never_touches_the_real_codex_home(env, spy):
    cli.main(["codex"])
    real = env / "real-codex"
    assert (real / "config.toml").read_text() == 'model = "old"\n'
    assert not (real / "p-models.json").exists()


def test_a_launch_never_touches_the_real_claude_home(env, spy):
    cli.main(["claude"])
    real = env / "real-claude"
    assert json.loads((real / "settings.json").read_text()) == {"model": "opus"}


def test_extra_arguments_reach_the_harness(env, spy):
    assert cli.main(["claude", "--", "--model", "a/one"]) == 0
    assert spy["args"] == ["--model", "a/one"]


def test_a_named_profile_gets_its_own_home(env, spy):
    (env / "profiles.toml").write_text(
        'active = "p"\n\n[profiles.p]\nbase_url = "http://h/v1"\nwire_api = "chat"\n'
        '\n[profiles.q]\nbase_url = "http://h/v1"\nwire_api = "chat"\n'
    )
    cli.main(["codex", "--profile", "q"])
    assert spy["home"].endswith("homes/q/codex")


def test_apply_writes_the_real_codex_home(env, spy):
    assert cli.main(["codex", "apply"]) == 0
    real = env / "real-codex"
    assert (real / "p-models.json").exists()
    assert "model_provider" in (real / "config.toml").read_text()
    assert "command" not in spy


def test_apply_writes_the_real_claude_home(env, spy):
    assert cli.main(["claude", "apply"]) == 0
    data = json.loads((env / "real-claude" / "settings.json").read_text())
    assert "modelPicker" in data
    assert data["env"]["ANTHROPIC_BASE_URL"] == "http://h/v1"
    assert "command" not in spy


def test_apply_accepts_a_dry_run(env, spy):
    assert cli.main(["codex", "apply", "--dry-run"]) == 0
    assert not (env / "real-codex" / "p-models.json").exists()


def test_apply_accepts_a_reset(env, spy):
    cli.main(["claude", "apply"])
    assert cli.main(["claude", "apply", "--reset"]) == 0
    data = json.loads((env / "real-claude" / "settings.json").read_text())
    assert "modelPicker" not in data


def test_an_unreachable_endpoint_stops_a_launch(env, spy, monkeypatch):
    from xsync_cli.sources.openai_compat import EndpointUnreachable

    def failing(*args, **kwargs):
        raise EndpointUnreachable("refused")

    monkeypatch.setattr(cli, "fetch_models", failing)
    assert cli.main(["codex"]) == 2
    assert "command" not in spy


def test_yolo_bypasses_the_claude_permission_prompt(env, spy):
    assert cli.main(["claude", "--yolo"]) == 0
    assert spy["args"] == ["--dangerously-skip-permissions"]


def test_yolo_bypasses_the_codex_approval_prompt(env, spy):
    assert cli.main(["codex", "--yolo"]) == 0
    assert spy["args"] == ["--dangerously-bypass-approvals-and-sandbox"]


def test_yolo_keeps_the_arguments_of_the_user(env, spy):
    assert cli.main(["claude", "--yolo", "--", "--model", "a/one"]) == 0
    assert spy["args"] == ["--dangerously-skip-permissions", "--model", "a/one"]


def test_yolo_never_repeats_a_flag_the_user_gave(env, spy):
    assert cli.main(["claude", "--yolo", "--", "--dangerously-skip-permissions"]) == 0
    assert spy["args"] == ["--dangerously-skip-permissions"]
