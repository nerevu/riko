"""
Smoke-tests bucket_plan.py on a throwaway repository.

Run after editing bucket_plan.py:

    uv run --active pytest .claude/skills/land/test_bucket_plan.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import bucket_plan
import rehearse_plan
import split_hunks

BUCKETS = """
default = "feature"

[[bucket]]
name = "lock"
message = "[DEV] Upgrade locked dependencies"

[[bucket]]
name = "fix"
fixup = "abc123"

[[bucket]]
name = "rename"
message = '''
[REFACTOR] Rename old_name

- Also rename its caller
'''

[[bucket]]
name = "feature"
message = "[NEW] Add the feature"

[[bucket]]
name = "unused"
message = "[DEV] Nothing lands here"

[[bucket]]
name = "scratch"
skip = true
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Leaves a change in ``tmp_path/repo``; rules and plans go beside it."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        config = ("-c", "user.name=t", "-c", "user.email=t@t")
        cmd = (split_hunks.GIT, *config, *args)
        subprocess.run(cmd, check=True, capture_output=True)

    monkeypatch.chdir(root)
    monkeypatch.setattr(split_hunks, "BASE", split_hunks.BASE)
    git("init", "-q")
    (root / "uv.lock").write_text("v1\n")
    (root / "a.py").write_text("x = old_name()\n\n\n\n\ny = 1\n\n\n\n\nz = 2\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    (root / "uv.lock").write_text("v2\n")
    (root / "a.py").write_text("x = new_name()\n\n\n\n\ny = 3\n\n\n\n\nz = 4\n")
    (root / "b.py").write_text("b = 1\n")
    (root / "notes.md").write_text("scratch\n")
    return tmp_path


def test_rules_sort_every_hunk_into_its_step(repo, capsys):
    rules = repo / "rules.toml"
    rules.write_text(
        BUCKETS
        + """
[[rule]]
bucket = "lock"
path = '^uv\\.lock$'

[[rule]]
bucket = "fix"
ids = ["a.py:11"]

[[rule]]
bucket = "rename"
path = '\\.py$'
swaps = [["old_name", "new_name"]]

[[rule]]
bucket = "fix"
body = '^y = 3$'

[[rule]]
bucket = "scratch"
ids = ["notes.md"]
"""
    )
    out = repo / "plan"

    assert bucket_plan.main([str(rules), "--out", str(out)]) == 0
    assert (out / "plan.txt").read_text().splitlines() == [
        "commit lock.msg",
        "uv.lock:1",
        "fixup abc123",
        "a.py:6",
        "a.py:11",
        "commit rename.msg",
        "a.py:1",
        "commit feature.msg",
        "b.py",
        "skip",
        "notes.md",
    ]
    steps = rehearse_plan.read_plan(out / "plan.txt")
    assert [(step.kind, step.arg) for step in steps] == [
        ("commit", "lock.msg"),
        ("fixup", "abc123"),
        ("commit", "rename.msg"),
        ("commit", "feature.msg"),
        ("skip", ""),
    ]
    message = "[REFACTOR] Rename old_name\n\n- Also rename its caller\n"
    assert (out / "rename.msg").read_text() == message
    assert not (out / "fix.msg").exists()
    assert not (out / "unused.msg").exists()
    assert "unused" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param('[[rule]]\nbucket = "missing"\npath = "a"\n', id="unknown-bucket"),
        pytest.param('[[rule]]\nbucket = "fix"\npaths = "a"\n', id="unknown-key"),
        pytest.param('[[rule]]\nbucket = "fix"\nids = ["c.py"]\n', id="unknown-id"),
        pytest.param(
            '[[bucket]]\nname = "both"\nmessage = "m"\nskip = true\n', id="two-kinds"
        ),
    ],
)
def test_malformed_rules_exit(repo, extra):
    rules = repo / "rules.toml"
    rules.write_text(BUCKETS + extra)

    with pytest.raises(SystemExit):
        bucket_plan.main([str(rules), "--out", str(repo / "plan")])
