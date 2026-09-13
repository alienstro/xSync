"""The safe file write."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, payload: dict[str, Any], keep_backup: bool = True) -> None:
    """Write JSON without a partial file.

    The function writes a temporary file in the same directory, confirms
    that the file holds valid JSON, and then replaces the target. It
    keeps one backup with the suffix `.bak`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    json.loads(text)

    temporary.write_text(text, encoding="utf-8")
    if keep_backup and path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(path.read_bytes())
    os.replace(temporary, path)
