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
    # The level stays a string. Codex stops on a null here.
    assert entry["default_reasoning_level"] == "medium"


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


def test_the_context_percent_matches_the_working_catalog():
    assert render_entry(model(), RULES)["effective_context_window_percent"] == 95


def test_the_truncation_policy_is_the_working_object():
    assert render_entry(model(), RULES)["truncation_policy"] == {
        "mode": "tokens",
        "limit": 10000,
    }


def test_the_reasoning_summary_default_matches_the_working_catalog():
    assert render_entry(model(), RULES)["default_reasoning_summary"] == "none"


def test_the_skills_instruction_flag_matches_the_working_catalog():
    assert render_entry(model(), RULES)["include_skills_usage_instructions"] is False


def test_verbosity_and_image_detail_match_the_working_catalog():
    entry = render_entry(model(), RULES)
    assert entry["support_verbosity"] is True
    assert entry["supports_image_detail_original"] is True


def test_model_messages_holds_the_instructions_template():
    messages = render_entry(model(), RULES)["model_messages"]
    assert isinstance(messages, dict)
    assert messages["instructions_template"].startswith("You are Codex")
    assert "instructions_variables" in messages


def test_a_named_model_gets_its_own_model_messages():
    special = render_entry(model(slug="cx/gpt-5.5"), RULES)["model_messages"]
    generic = render_entry(model(slug="cx/other"), RULES)["model_messages"]
    assert special != generic
    assert len(special["instructions_template"]) > len(generic["instructions_template"])


def test_a_plain_model_gets_no_speed_tier():
    entry = render_entry(model(), RULES)
    assert entry["additional_speed_tiers"] == []
    assert entry["service_tiers"] == []


def test_the_named_openai_models_keep_their_tiers():
    for slug, priority, verbosity in (
        ("cx/gpt-5.5", 18, "low"),
        ("cx/gpt-5.4", 14, "low"),
    ):
        entry = render_entry(model(slug=slug), RULES)
        assert entry["additional_speed_tiers"] == ["fast"]
        assert entry["service_tiers"] == [
            {"id": "priority", "name": "Fast", "description": "1.5x speed, increased usage"}
        ]
        assert entry["priority"] == priority
        assert entry["default_verbosity"] == verbosity


def test_only_gpt_5_5_asks_for_the_skills_instructions():
    assert render_entry(model(slug="cx/gpt-5.5"), RULES)[
        "include_skills_usage_instructions"
    ] is True
    assert render_entry(model(slug="cx/gpt-5.4"), RULES)[
        "include_skills_usage_instructions"
    ] is False


def test_the_search_tool_type_is_never_null():
    """Codex accepts a string or a map here. A null stops Codex."""
    for search in (True, False):
        entry = render_entry(model(search=search), RULES)
        assert entry["web_search_tool_type"] == "text_and_image"


def test_the_reasoning_level_is_never_null():
    """Codex accepts a string here. A null stops Codex."""
    for reasoning in (True, False):
        entry = render_entry(model(reasoning=reasoning), RULES)
        assert isinstance(entry["default_reasoning_level"], str)


def test_only_the_known_fields_may_hold_a_null():
    """The working catalog holds a null in two fields only."""
    allowed = {"availability_nux", "upgrade"}
    for slug in ("cmc/a/b", "cx/gpt-5.5"):
        for reasoning in (True, False):
            for search in (True, False):
                entry = render_entry(
                    model(slug=slug, reasoning=reasoning, search=search), RULES
                )
                nulls = {k for k, v in entry.items() if v is None}
                assert nulls <= allowed, f"{slug} has an unexpected null: {nulls}"


def test_a_plain_model_still_reports_no_search():
    assert render_entry(model(search=False), RULES)["supports_search_tool"] is False
