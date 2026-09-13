"""The provider-neutral model record."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Model:
    """One model, as an endpoint reports it.

    The fields hold facts about the model. They do not hold harness
    settings. An endpoint that reports no capabilities gives None or
    False. The adapter rules then supply a value.
    """

    slug: str
    context_window: int | None
    max_output: int | None
    vision: bool
    reasoning: bool
    tools: bool
    search: bool
    owned_by: str | None

    @property
    def prefix(self) -> str:
        """The first slug segment, or an empty string for a flat slug."""
        head, sep, _ = self.slug.partition("/")
        return head if sep else ""

    @property
    def leaf_name(self) -> str:
        """The last slug segment."""
        return self.slug.rsplit("/", 1)[-1]
