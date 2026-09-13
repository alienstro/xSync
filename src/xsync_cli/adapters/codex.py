"""The Codex adapter.

This module turns Model objects into the Codex model catalog. It knows
nothing about HTTP.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from xsync_cli.core.model import Model

REASONING_LEVELS = [
    {"effort": "low", "description": "Fast responses with lighter reasoning"},
    {
        "effort": "medium",
        "description": "Balances speed and reasoning depth for everyday tasks",
    },
    {"effort": "high", "description": "Greater reasoning depth for complex problems"},
    {
        "effort": "xhigh",
        "description": "Extra high reasoning depth for complex problems",
    },
]


class AdapterError(Exception):
    """The rules file or the prompt data is wrong."""


def _read_prompt(name: str) -> str:
    try:
        return files("xsync_cli.adapters.prompts").joinpath(name).read_text(
            encoding="utf-8"
        )
    except FileNotFoundError:
        raise AdapterError(f"the prompt file {name!r} is absent from the package.") from None


@dataclass(frozen=True, slots=True)
class Rules:
    """The three rule layers."""

    defaults: dict[str, Any]
    prefixes: dict[str, dict[str, Any]]
    slugs: dict[str, dict[str, Any]]

    def for_model(self, model: Model) -> dict[str, Any]:
        """The merged rule values for one model."""
        merged: dict[str, Any] = dict(self.defaults)
        merged.update(self.prefixes.get(model.prefix, {}))
        merged.update(self.slugs.get(model.slug, {}))
        return merged


def load_rules(path: Path | None = None) -> Rules:
    """Read the rules file. The default file is package data."""
    if path is None:
        text = files("xsync_cli.adapters.rules").joinpath("codex.toml").read_text(
            encoding="utf-8"
        )
    else:
        text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return Rules(
        defaults=dict(data.get("defaults", {})),
        prefixes={k: dict(v) for k, v in (data.get("prefix") or {}).items()},
        slugs={k: dict(v) for k, v in (data.get("slug") or {}).items()},
    )


def _display_name(model: Model) -> str:
    words = model.leaf_name.replace("_", "-").split("-")
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


def render_entry(model: Model, rules: Rules) -> dict[str, Any]:
    """One Codex catalog entry."""
    values = rules.for_model(model)
    context_window = model.context_window or values["default_context_window"]
    modalities = ["text", "image"] if model.vision else ["text"]

    return {
        "slug": model.slug,
        "display_name": values.get("display_name") or _display_name(model),
        "description": str(values["description_template"]).format(slug=model.slug),
        "default_reasoning_level": "medium" if model.reasoning else None,
        "supported_reasoning_levels": (
            [dict(level) for level in REASONING_LEVELS] if model.reasoning else []
        ),
        "shell_type": values["shell_type"],
        "visibility": values["visibility"],
        "supported_in_api": values["supported_in_api"],
        "priority": values["priority"],
        "additional_speed_tiers": [],
        "service_tiers": [],
        "availability_nux": None,
        "upgrade": None,
        "base_instructions": _read_prompt(values["base_instructions_file"]),
        "model_messages": [],
        "include_skills_usage_instructions": values[
            "include_skills_usage_instructions"
        ],
        "supports_reasoning_summaries": (
            bool(values["supports_reasoning_summaries"]) and model.reasoning
        ),
        "default_reasoning_summary": values["default_reasoning_summary"],
        "support_verbosity": values["support_verbosity"],
        "default_verbosity": values["default_verbosity"],
        "apply_patch_tool_type": values["apply_patch_tool_type"],
        "web_search_tool_type": values["web_search_tool_type"] if model.search else None,
        "truncation_policy": values["truncation_policy"],
        "supports_parallel_tool_calls": model.tools,
        "supports_image_detail_original": values["supports_image_detail_original"],
        "context_window": context_window,
        "max_context_window": context_window,
        "effective_context_window_percent": values["effective_context_window_percent"],
        "experimental_supported_tools": [],
        "input_modalities": modalities,
        "supports_search_tool": model.search,
        "use_responses_lite": values["use_responses_lite"],
    }


def render_catalog(models: Sequence[Model], rules: Rules) -> dict[str, Any]:
    """The whole Codex catalog document."""
    return {"models": [render_entry(model, rules) for model in models]}
