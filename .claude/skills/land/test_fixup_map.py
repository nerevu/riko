"""
Smoke-tests fixup_map.py's fold leads on a throwaway tree.

Run after editing fixup_map.py:

    uv run --active pytest .claude/skills/land/test_fixup_map.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fixup_map


def test_fixes_lists_the_branch_commit_a_fix_repairs(tmp_path, monkeypatch, capsys):
    def git(*args):
        config = ("-c", "user.name=t", "-c", "user.email=t@t")
        cmd = ("git", *config, "-c", "core.hooksPath=/dev/null", *args)
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    def commit(text, message):
        (tmp_path / "riko" / "a.py").write_text(text)
        git("add", "riko")
        git("commit", "-q", "-m", message)
        return git("rev-parse", "HEAD").strip()

    monkeypatch.chdir(tmp_path)
    (tmp_path / "riko").mkdir()
    git("init", "-q", "-b", "next")
    commit("a = 1\nb = 2\n", "base")
    git("checkout", "-q", "-b", "topic")
    intro = commit("a = 1\nb = 3\n", "[REFACTOR] Introduce the bug")
    fix = commit("a = 1\nb = 4\n", "[FIX] Repair the bug")
    monkeypatch.setattr(sys, "argv", ["fixup_map.py", "--fixes"])
    fixup_map.main()
    out = capsys.readouterr().out.splitlines()
    assert out[3:] == [
        f"  {fix[:10]} [FIX] Repair the bug",
        f"       1  {intro[:10]} [REFACTOR] Introduce the bug",
    ]
