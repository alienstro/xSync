from importlib.resources import files


def test_the_rules_file_is_package_data():
    text = files("xsync_cli.adapters.rules").joinpath("codex.toml").read_text()
    assert "[defaults]" in text


def test_the_generic_prompt_is_package_data():
    text = files("xsync_cli.adapters.prompts").joinpath("generic-codex.md").read_text()
    assert text.startswith("You are Codex")
    assert len(text) > 5000


def test_each_named_prompt_exists():
    for name in ("gpt-5.5.md", "gpt-5.4.md"):
        text = files("xsync_cli.adapters.prompts").joinpath(name).read_text()
        assert text.startswith("You are Codex")
