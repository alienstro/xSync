from xsync_cli.core.filters import apply_filters
from xsync_cli.core.model import Model


def model(slug: str) -> Model:
    return Model(
        slug=slug,
        context_window=1000,
        max_output=100,
        vision=False,
        reasoning=False,
        tools=True,
        search=False,
        owned_by=None,
    )


MODELS = [
    model("cmc/deepseek/deepseek-v4-pro"),
    model("cmc/text-embedding-3-small"),
    model("cx/gpt-5.5"),
]


def test_no_rule_keeps_every_model():
    assert apply_filters(MODELS, [], []) == MODELS


def test_exclude_removes_a_matching_slug():
    kept = apply_filters(MODELS, [], ["*embedding*"])
    assert [m.slug for m in kept] == [
        "cmc/deepseek/deepseek-v4-pro",
        "cx/gpt-5.5",
    ]


def test_include_keeps_only_a_matching_slug():
    kept = apply_filters(MODELS, ["cx/*"], [])
    assert [m.slug for m in kept] == ["cx/gpt-5.5"]


def test_exclude_wins_over_include():
    kept = apply_filters(MODELS, ["cmc/*"], ["*embedding*"])
    assert [m.slug for m in kept] == ["cmc/deepseek/deepseek-v4-pro"]


def test_the_match_ignores_the_letter_case():
    kept = apply_filters([model("CX/GPT-5.5")], ["cx/*"], [])
    assert len(kept) == 1


def test_the_order_of_the_input_stays():
    kept = apply_filters(MODELS, [], [])
    assert kept is not MODELS
    assert [m.slug for m in kept] == [m.slug for m in MODELS]
