"""Copy the base_instructions values out of an existing Codex catalog.

Run this tool one time. It fills `src/xsync_cli/adapters/prompts/`.

    python tools/extract_prompts.py ~/.codex/9router-models.json
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "src/xsync_cli/adapters/prompts"
NAMES = {
    "cx/gpt-5.5": "gpt-5.5.md",
    "cx/gpt-5.4": "gpt-5.4.md",
}


def main(catalog_path: str) -> int:
    models = json.loads(Path(catalog_path).read_text(encoding="utf-8"))["models"]
    TARGET.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[str]] = collections.defaultdict(list)
    for model in models:
        groups[model.get("base_instructions", "")].append(model["slug"])

    largest = max(groups.items(), key=lambda item: len(item[1]))
    (TARGET / "generic-codex.md").write_text(largest[0], encoding="utf-8")
    print(f"generic-codex.md  {len(largest[0])} chars  {len(largest[1])} models")

    by_slug = {model["slug"]: model.get("base_instructions", "") for model in models}
    for slug, filename in NAMES.items():
        text = by_slug.get(slug)
        if not text:
            print(f"skip {slug}: not in the catalog")
            continue
        (TARGET / filename).write_text(text, encoding="utf-8")
        print(f"{filename}  {len(text)} chars")

    write_model_messages(models)
    return 0


def write_model_messages(models: list[dict]) -> None:
    """Copy the model_messages objects out of the catalog.

    The object holds a second prompt. It has the same three variants as
    base_instructions.
    """
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for model in models:
        groups[json.dumps(model.get("model_messages"), sort_keys=True)].append(
            model["slug"]
        )

    largest = max(groups.items(), key=lambda item: len(item[1]))
    (TARGET / "generic-codex.messages.json").write_text(largest[0], encoding="utf-8")
    print(
        f"generic-codex.messages.json  {len(largest[0])} chars  "
        f"{len(largest[1])} models"
    )

    by_slug = {model["slug"]: model.get("model_messages") for model in models}
    for slug, filename in NAMES.items():
        messages = by_slug.get(slug)
        if not messages:
            print(f"skip {slug} messages: not in the catalog")
            continue
        name = filename.replace(".md", ".messages.json")
        text = json.dumps(messages, sort_keys=True)
        (TARGET / name).write_text(text, encoding="utf-8")
        print(f"{name}  {len(text)} chars")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
