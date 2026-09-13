"""The include and exclude glob rules."""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch

from xsync_cli.core.model import Model


def _matches_any(slug: str, patterns: Sequence[str]) -> bool:
    lowered = slug.lower()
    return any(fnmatch(lowered, pattern.lower()) for pattern in patterns)


def apply_filters(
    models: Sequence[Model],
    include: Sequence[str],
    exclude: Sequence[str],
) -> list[Model]:
    """Keep the models that the rules allow.

    An empty include list keeps every model. The exclude list always
    wins over the include list. The match ignores the letter case.
    """
    kept: list[Model] = []
    for candidate in models:
        if include and not _matches_any(candidate.slug, include):
            continue
        if exclude and _matches_any(candidate.slug, exclude):
            continue
        kept.append(candidate)
    return kept
