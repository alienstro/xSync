"""The difference between two catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogDiff:
    """The report of one sync."""

    added: list[str]
    removed: list[str]
    changed: list[tuple[str, list[str]]]
    unchanged: list[str]

    @property
    def is_empty(self) -> bool:
        """True when the catalog does not change."""
        return not (self.added or self.removed or self.changed)

    def render(self, limit: int = 8) -> str:
        """The report as text."""
        lines: list[str] = []
        if self.added:
            lines.append(f"+ {len(self.added)} added      {self._sample(self.added, limit)}")
        if self.removed:
            lines.append(
                f"- {len(self.removed)} removed    {self._sample(self.removed, limit)}"
            )
        if self.changed:
            names = [f"{slug} ({', '.join(fields)})" for slug, fields in self.changed]
            lines.append(f"~ {len(self.changed)} changed    {self._sample(names, limit)}")
        lines.append(f"  {len(self.unchanged)} unchanged")
        return "\n".join(lines)

    @staticmethod
    def _sample(items: list[str], limit: int) -> str:
        head = ", ".join(items[:limit])
        return head if len(items) <= limit else f"{head}, … (+{len(items) - limit})"


def _by_slug(catalog: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not catalog:
        return {}
    return {entry["slug"]: entry for entry in catalog.get("models", []) if "slug" in entry}


def diff_catalogs(old: dict[str, Any] | None, new: dict[str, Any]) -> CatalogDiff:
    """Compare two catalogs by slug."""
    old_map = _by_slug(old)
    new_map = _by_slug(new)

    added = [slug for slug in new_map if slug not in old_map]
    removed = [slug for slug in old_map if slug not in new_map]
    changed: list[tuple[str, list[str]]] = []
    unchanged: list[str] = []

    for slug, entry in new_map.items():
        if slug not in old_map:
            continue
        fields = sorted(
            key
            for key in set(entry) | set(old_map[slug])
            if entry.get(key) != old_map[slug].get(key)
        )
        if fields:
            changed.append((slug, fields))
        else:
            unchanged.append(slug)

    return CatalogDiff(added=added, removed=removed, changed=changed, unchanged=unchanged)
