from xsync_cli.core.diff import diff_catalogs


def catalog(*entries) -> dict:
    return {"models": list(entries)}


def entry(slug: str, **kw) -> dict:
    base = {"slug": slug, "context_window": 1000, "priority": 5}
    base.update(kw)
    return base


def test_an_absent_old_catalog_makes_everything_added():
    result = diff_catalogs(None, catalog(entry("a"), entry("b")))
    assert result.added == ["a", "b"]
    assert result.removed == []


def test_a_removed_model_appears_in_removed():
    result = diff_catalogs(catalog(entry("a"), entry("b")), catalog(entry("a")))
    assert result.removed == ["b"]
    assert result.unchanged == ["a"]


def test_a_changed_field_appears_with_its_name():
    result = diff_catalogs(
        catalog(entry("a", context_window=1000)),
        catalog(entry("a", context_window=2000)),
    )
    assert result.changed == [("a", ["context_window"])]


def test_an_equal_catalog_is_empty():
    result = diff_catalogs(catalog(entry("a")), catalog(entry("a")))
    assert result.is_empty is True


def test_the_report_names_the_counts():
    result = diff_catalogs(catalog(entry("a")), catalog(entry("b")))
    text = result.render()
    assert "1 added" in text
    assert "1 removed" in text


def test_a_changed_model_shows_only_a_few_field_names():
    old = catalog(entry("a", **{f"f{i}": i for i in range(10)}))
    new = catalog(entry("a", **{f"f{i}": i + 1 for i in range(10)}))
    text = diff_catalogs(old, new).render()
    assert "+7 more" in text
