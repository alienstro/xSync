"""The Claude Code adapter.

Claude Code holds no catalog file. It reads the rows of the `/model`
picker from `modelPicker.options` in `settings.json`. This module makes
those rows. It knows nothing about HTTP.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from xsync_cli.core.model import Model


@dataclass(frozen=True, slots=True)
class Rules:
    """The four rule layers, and the list of native model ids."""

    defaults: dict[str, Any]
    prefixes: dict[str, dict[str, Any]]
    names: dict[str, dict[str, Any]]
    slugs: dict[str, dict[str, Any]]

    def for_model(self, model: Model) -> dict[str, Any]:
        """The merged rule values for one model."""
        merged: dict[str, Any] = dict(self.defaults)
        merged.update(self.prefixes.get(model.prefix.lower(), {}))
        merged.update(self.names.get(model.leaf_name.lower(), {}))
        merged.update(self.slugs.get(model.slug, {}))
        return merged

    @property
    def native_ids(self) -> list[str]:
        """The model ids that Claude Code knows."""
        return [str(item).lower() for item in self.defaults.get("native_ids", [])]


def load_rules(path: Path | None = None) -> Rules:
    """Read the rules file. The default file is package data."""
    if path is None:
        text = files("xsync_cli.adapters.rules").joinpath("claude.toml").read_text(
            encoding="utf-8"
        )
    else:
        text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return Rules(
        defaults=dict(data.get("defaults", {})),
        prefixes={k.lower(): dict(v) for k, v in (data.get("prefix") or {}).items()},
        names={k.lower(): dict(v) for k, v in (data.get("name") or {}).items()},
        slugs={k: dict(v) for k, v in (data.get("slug") or {}).items()},
    )


def is_native(slug: str, rules: Rules) -> bool:
    """True when Claude Code already knows how to drive this model.

    Claude Code matches a known model id inside the name of the model.
    Therefore `ed3n/claude-sonnet-5` needs no map.
    """
    lowered = slug.lower()
    return any(known in lowered for known in rules.native_ids)


def _label(model: Model) -> str:
    words = model.leaf_name.replace("_", "-").split("-")
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


def render_rows(models: Sequence[Model], rules: Rules) -> list[dict[str, Any]]:
    """One picker row for each model.

    A row holds `behavesAs` only when Claude Code does not know the
    model. Claude Code refuses such a model without that field.
    """
    rows: list[dict[str, Any]] = []
    for model in models:
        values = rules.for_model(model)
        row: dict[str, Any] = {
            "model": model.slug,
            "label": values.get("label") or _label(model),
            "description": str(values["description_template"]).format(slug=model.slug),
        }
        if not is_native(model.slug, rules):
            row["behavesAs"] = values["behaves_as"]
        rows.append(row)
    return rows
