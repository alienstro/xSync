from xsync_cli.adapters.codex import load_rules, render_catalog, render_entry
from xsync_cli.core.model import Model


def model(slug="cmc/deepseek/deepseek-v4-pro", **kw) -> Model:
    base = dict(
        slug=slug,
        context_window=1000000,
        max_output=384000,
        vision=False,
        reasoning=True,
        tools=True,
        search=False,
        owned_by="cmc",
    )
    base.update(kw)
    return Model(**base)


RULES = load_rules()


def test_the_entry_carries_the_slug():
    assert render_entry(model(), RULES)["slug"] == "cmc/deepseek/deepseek-v4-pro"


def test_the_context_window_comes_from_the_endpoint():
    entry = render_entry(model(), RULES)
    assert entry["context_window"] == 1000000
    assert entry["max_context_window"] == 1000000


def test_an_absent_context_window_uses_the_default():
    entry = render_entry(model(context_window=None), RULES)
    assert entry["context_window"] == 128000


def test_a_reasoning_model_gets_four_levels():
    entry = render_entry(model(), RULES)
    efforts = [level["effort"] for level in entry["supported_reasoning_levels"]]
    assert efforts == ["low", "medium", "high", "xhigh"]
    assert entry["default_reasoning_level"] == "medium"


def test_a_plain_model_gets_no_level():
    entry = render_entry(model(reasoning=False), RULES)
    assert entry["supported_reasoning_levels"] == []
    assert entry["default_reasoning_level"] is None


def test_a_vision_model_accepts_an_image():
    assert render_entry(model(vision=True), RULES)["input_modalities"] == [
        "text",
        "image",
    ]


def test_a_plain_model_accepts_text_only():
    assert render_entry(model(), RULES)["input_modalities"] == ["text"]


def test_the_tool_flag_comes_from_the_endpoint():
    assert render_entry(model(), RULES)["supports_parallel_tool_calls"] is True
    assert render_entry(model(tools=False), RULES)["supports_parallel_tool_calls"] is False


def test_the_search_flag_controls_the_search_tool():
    assert render_entry(model(), RULES)["supports_search_tool"] is False
    assert render_entry(model(search=True), RULES)["supports_search_tool"] is True


def test_the_display_name_comes_from_the_last_segment():
    assert render_entry(model(), RULES)["display_name"] == "Deepseek V4 Pro"


def test_the_prefix_rule_wins_over_the_default():
    assert render_entry(model(slug="cx/other"), RULES)["priority"] == 10
    assert render_entry(model(), RULES)["priority"] == 5


def test_the_slug_rule_wins_over_the_prefix_rule():
    special = render_entry(model(slug="cx/gpt-5.5"), RULES)
    generic = render_entry(model(slug="cx/other"), RULES)
    assert special["base_instructions"] != generic["base_instructions"]
    assert len(special["base_instructions"]) > 20000


def test_the_catalog_holds_a_models_list():
    catalog = render_catalog([model(), model(slug="cx/gpt-5.5")], RULES)
    assert [entry["slug"] for entry in catalog["models"]] == [
        "cmc/deepseek/deepseek-v4-pro",
        "cx/gpt-5.5",
    ]


def test_every_required_field_is_present():
    required = {
        "slug",
        "display_name",
        "description",
        "default_reasoning_level",
        "supported_reasoning_levels",
        "shell_type",
        "visibility",
        "supported_in_api",
        "priority",
        "base_instructions",
        "context_window",
        "max_context_window",
        "input_modalities",
        "supports_parallel_tool_calls",
        "supports_search_tool",
    }
    assert required <= set(render_entry(model(), RULES))
