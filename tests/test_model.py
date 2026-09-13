from xsync_cli.core.model import Model


def make(**kw) -> Model:
    base = dict(
        slug="cmc/deepseek/deepseek-v4-pro",
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


def test_prefix_is_first_slug_segment():
    assert make().prefix == "cmc"


def test_prefix_of_flat_slug_is_empty():
    assert make(slug="gpt-4o").prefix == ""


def test_leaf_name_is_last_slug_segment():
    assert make().leaf_name == "deepseek-v4-pro"


def test_leaf_name_of_flat_slug_is_the_slug():
    assert make(slug="gpt-4o").leaf_name == "gpt-4o"


def test_model_is_frozen():
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        make().slug = "other"
