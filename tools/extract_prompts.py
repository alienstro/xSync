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
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
