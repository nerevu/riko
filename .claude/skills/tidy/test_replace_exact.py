"""
Smoke-tests replace_exact.py.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_replace_exact.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from replace_exact import apply_replacements, main


def test_applies_replacements_in_order() -> None:
    text, errors = apply_replacements("a b a", [["a", "c", 2], ["c b", "d", 1]])
    assert (text, errors) == ("d c", [])


def test_a_count_mismatch_writes_nothing(tmp_path: Path) -> None:
    target, spec = tmp_path / "doc.md", tmp_path / "spec.json"
    target.write_text("GraphIndex and GraphIndex")
    spec.write_text(json.dumps([["GraphIndex", "WorkflowIndex", 1]]))

    assert main([str(target), str(spec)]) == 1
    assert target.read_text() == "GraphIndex and GraphIndex"
