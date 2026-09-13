from xsync_cli.adapters.claude import load_rules, render_rows
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


def row(slug: str) -> dict:
    return render_rows([model(slug=slug)], RULES)[0]


def test_the_row_carries_the_model_word_for_word():
    assert row("cmc/deepseek/deepseek-v4-pro")["model"] == "cmc/deepseek/deepseek-v4-pro"


def test_an_unknown_model_gets_a_behaves_as():
    assert row("cmc/deepseek/deepseek-v4-pro")["behavesAs"] == "claude-opus-4-8"


def test_a_claude_model_keeps_its_native_handling():
    assert "behavesAs" not in row("ed3n/claude-sonnet-5")


def test_every_claude_family_model_stays_native():
    for slug in (
        "ed3n/claude-opus-5",
        "ed3n/claude-opus-4-8",
        "ed3n/claude-opus-4-6",
        "ed3n/claude-sonnet-5",
        "ed3n/claude-sonnet-4-6",
        "ed3n/claude-sonnet-4-5-20250929",
        "ed3n/claude-haiku-4-5-20251001",
    ):
        assert "behavesAs" not in row(slug), slug


def test_the_native_check_ignores_the_letter_case():
    assert "behavesAs" not in row("ED3N/Claude-Sonnet-5")


def test_a_fast_model_behaves_as_a_small_model():
    assert row("cmc/deepseek/deepseek-v4.1-flash")["behavesAs"] == "claude-haiku-4-5"


def test_a_name_rule_works_on_every_router():
    for slug in ("cmc/deepseek/deepseek-v4.1-flash", "other/deepseek-v4.1-flash"):
        assert row(slug)["behavesAs"] == "claude-haiku-4-5"


def test_the_label_reads_as_a_title():
    assert row("cmc/deepseek/deepseek-v4-pro")["label"] == "Deepseek V4 Pro"


def test_the_description_names_the_model():
    assert row("cmc/deepseek/deepseek-v4-pro")["description"] == (
        "cmc/deepseek/deepseek-v4-pro"
    )


def test_the_rows_keep_the_order_of_the_models():
    rows = render_rows([model(slug="b/two"), model(slug="a/one")], RULES)
    assert [r["model"] for r in rows] == ["b/two", "a/one"]


def test_a_row_holds_no_other_field():
    assert set(row("cmc/deepseek/deepseek-v4-pro")) <= {
        "model",
        "label",
        "description",
        "behavesAs",
    }
