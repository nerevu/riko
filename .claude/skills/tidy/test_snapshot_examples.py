"""
Smoke-tests snapshot_examples.py on a tiny fake example module.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_snapshot_examples.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import snapshot_examples

FAKE_EXAMPLE = """
import sys

from riko.base._logging import get_logger

logger = get_logger("riko.modules.fake_example")


def pipe(test=False):
    logger.warning("USD/ rate not found in rates")
    sys.stderr.write("plain stderr\\n")
    return [{"rate": 1}]


def main(*, test=False):
    print("printed", object())
"""


@pytest.fixture
def fake_example(tmp_path, monkeypatch):
    (tmp_path / "fake_example.py").write_text(FAKE_EXAMPLE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(snapshot_examples, "NAMES", ("fake_example",))
    monkeypatch.setattr(snapshot_examples, "SCRIPTS", ())
    yield tmp_path
    sys.modules.pop("fake_example", None)


def test_capture_records_items_logs_stderr_and_prints(fake_example):
    text = snapshot_examples.capture()

    assert "=== fake_example sync" in text
    assert "] in fake_example:" in text
    assert "USD/ rate not found in rates" in text
    assert "plain stderr" in text
    assert "[{'rate': 1}]" in text
    assert "printed <object object at 0x..>" in text
    assert "=== fake_example async" not in text
    assert not isinstance(snapshot_examples.going.handlers["high"].stream, io.StringIO)


def test_compare_exits_1_on_a_changed_line_and_0_when_identical(fake_example, capsys):
    snapshot = fake_example / "before.txt"

    assert snapshot_examples.main([str(snapshot)]) == 0
    assert snapshot_examples.main(["--compare", str(snapshot)]) == 0

    snapshot.write_text(snapshot.read_text().replace("'rate': 1", "'rate': 2"))
    capsys.readouterr()

    assert snapshot_examples.main(["--compare", str(snapshot)]) == 1
    out = capsys.readouterr().out
    assert "-[{'rate': 2}]" in out
    assert "+[{'rate': 1}]" in out
