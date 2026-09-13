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


def test_a_built_wheel_holds_every_data_file():
    """The wheel must carry the rules file and every prompt.

    The test skips when no wheel exists. Run `uv build` first.
    """
    import pathlib
    import zipfile

    import pytest

    wheels = sorted(pathlib.Path("dist").glob("*.whl"))
    if not wheels:
        pytest.skip("no wheel in dist/. Run `uv build` first.")

    names = zipfile.ZipFile(wheels[-1]).namelist()
    required = (
        "adapters/rules/codex.toml",
        "adapters/prompts/generic-codex.md",
        "adapters/prompts/gpt-5.5.md",
        "adapters/prompts/gpt-5.4.md",
        "adapters/prompts/generic-codex.messages.json",
        "adapters/prompts/gpt-5.5.messages.json",
        "adapters/prompts/gpt-5.4.messages.json",
    )
    for item in required:
        assert any(item in name for name in names), f"{item} is absent from the wheel"
