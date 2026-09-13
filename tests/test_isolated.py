import json
import tomllib

from xsync_cli.adapters.isolated import prepare_claude_home, prepare_codex_home
from xsync_cli.core.model import Model
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


def model(slug="a/one") -> Model:
    return Model(
        slug=slug,
        context_window=1000,
        max_output=100,
        vision=False,
        reasoning=True,
        tools=True,
        search=False,
        owned_by="a",
    )


REAL_CODEX = """\
model = "gpt-old"
model_reasoning_effort = "max"

[projects."/Users/x/one"]
trust_level = "trusted"
"""

REAL_CLAUDE = {
    "model": "opus[1m]",
    "env": {"NODE_OPTIONS": "--max-old-space-size=512"},
    "hooks": {"Stop": [{"matcher": "*"}]},
}


def build_real_codex(tmp_path):
    real = tmp_path / "real-codex"
    (real / "skills").mkdir(parents=True)
    (real / "skills" / "s.md").write_text("skill")
    (real / "config.toml").write_text(REAL_CODEX)
    (real / "AGENTS.md").write_text("agents")
    return real


def build_real_claude(tmp_path):
    real = tmp_path / "real-claude"
    (real / "plugins").mkdir(parents=True)
    (real / "settings.json").write_text(json.dumps(REAL_CLAUDE))
    (real / "CLAUDE.md").write_text("rules")
    return real


def test_the_codex_home_holds_its_own_catalog(tmp_path):
    home = tmp_path / "home"
    prepare_codex_home(home, build_real_codex(tmp_path), profile(), "sk-1", [model()])
    catalog = json.loads((home / "9router-models.json").read_text())
    assert [m["slug"] for m in catalog["models"]] == ["a/one"]


def test_the_codex_home_points_at_the_endpoint(tmp_path):
    home = tmp_path / "home"
    prepare_codex_home(home, build_real_codex(tmp_path), profile(), "sk-1", [model()])
    data = tomllib.loads((home / "config.toml").read_text())
    assert data["model_provider"] == "9router"
    assert data["model_providers"]["9router"]["base_url"] == "http://127.0.0.1:20128/v1"
    assert data["model_providers"]["9router"]["wire_api"] == "responses"
    assert data["model_catalog_json"] == str(home / "9router-models.json")


def test_the_codex_home_keeps_the_trusted_projects(tmp_path):
    home = tmp_path / "home"
    prepare_codex_home(home, build_real_codex(tmp_path), profile(), "sk-1", [model()])
    data = tomllib.loads((home / "config.toml").read_text())
    assert "/Users/x/one" in data["projects"]
    assert data["model_reasoning_effort"] == "max"


def test_the_codex_home_shares_the_skills(tmp_path):
    home = tmp_path / "home"
    prepare_codex_home(home, build_real_codex(tmp_path), profile(), "sk-1", [model()])
    assert (home / "skills").is_symlink()
    assert (home / "skills" / "s.md").read_text() == "skill"


def test_the_real_codex_home_does_not_change(tmp_path):
    real = build_real_codex(tmp_path)
    before = (real / "config.toml").read_text()
    prepare_codex_home(tmp_path / "home", real, profile(), "sk-1", [model()])
    assert (real / "config.toml").read_text() == before
    assert not (real / "9router-models.json").exists()


def test_the_codex_home_works_without_a_real_home(tmp_path):
    home = tmp_path / "home"
    prepare_codex_home(home, tmp_path / "absent", profile(), None, [model()])
    data = tomllib.loads((home / "config.toml").read_text())
    assert data["model_provider"] == "9router"
    assert "http_headers" not in data["model_providers"]["9router"]


def test_the_claude_home_holds_the_picker_rows(tmp_path):
    home = tmp_path / "home"
    prepare_claude_home(home, build_real_claude(tmp_path), profile(), "sk-1", [model()])
    data = json.loads((home / "settings.json").read_text())
    assert [r["model"] for r in data["modelPicker"]["options"]] == ["a/one"]
    assert data["modelPicker"]["replaceBuiltInOptions"] is False


def test_the_claude_home_points_at_the_endpoint(tmp_path):
    home = tmp_path / "home"
    prepare_claude_home(home, build_real_claude(tmp_path), profile(), "sk-1", [model()])
    env = json.loads((home / "settings.json").read_text())["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:20128/v1"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-1"
    assert env["NODE_OPTIONS"] == "--max-old-space-size=512"


def test_the_claude_home_keeps_the_hooks(tmp_path):
    home = tmp_path / "home"
    prepare_claude_home(home, build_real_claude(tmp_path), profile(), "sk-1", [model()])
    data = json.loads((home / "settings.json").read_text())
    assert data["hooks"] == REAL_CLAUDE["hooks"]


def test_the_claude_home_shares_the_plugins_and_copies_the_rules(tmp_path):
    home = tmp_path / "home"
    prepare_claude_home(home, build_real_claude(tmp_path), profile(), "sk-1", [model()])
    assert (home / "plugins").is_symlink()
    assert (home / "CLAUDE.md").read_text() == "rules"


def test_the_real_claude_home_does_not_change(tmp_path):
    real = build_real_claude(tmp_path)
    before = (real / "settings.json").read_text()
    prepare_claude_home(tmp_path / "home", real, profile(), "sk-1", [model()])
    assert (real / "settings.json").read_text() == before
