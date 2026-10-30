"""
Smoke-tests overlap_scan.py's doctest sections on a throwaway repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_overlap_scan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import overlap_scan

CONFIG = '''\
def load_settings(env):
    """
    Loads settings.

    >>> load_settings({"RIKO_NODE_THREADS": "many"}).node_threads
    40
    >>> load_settings({"RIKO_NODE_THREADS": None})
    Traceback (most recent call last):
    ValueError: RIKO_NODE_THREADS must be a string
    """
'''

TESTS = """\
import pytest

ENV_OVERRIDES = [
    pytest.param("RIKO_NODE_THREADS", "-1", "node_threads", 40, id="int-below-min"),
]


class TestLoadSettings:
    @pytest.mark.parametrize(("key", "raw", "name", "expected"), ENV_OVERRIDES)
    def test_env_override_or_default(self, key, raw, name, expected):
        assert getattr(load_settings({key: raw}), name) == expected

    def test_a_non_string_is_refused(self):
        with pytest.raises(ValueError, match="must be a string"):
            load_settings({"RIKO_NODE_THREADS": None})
"""


def test_doctest_sections_pair_a_doctest_with_its_pytest_twin(tmp_path):
    (tmp_path / "riko").mkdir()
    (tmp_path / "riko" / "_config.py").write_text(CONFIG)
    tier = tmp_path / "tests" / "internal"
    tier.mkdir(parents=True)
    (tier / "test_values.py").write_text(TESTS)

    files = overlap_scan.load_test_files(tmp_path)
    examples = overlap_scan.build_examples(tmp_path)
    rows, raises = overlap_scan.build_rows(files)
    spread = overlap_scan.get_name_spread(files)
    args = list(overlap_scan.gen_doctest_args(examples, rows, spread))
    errors = list(overlap_scan.gen_doctest_raises(examples, raises))

    assert len(args) == len(errors) == 1
    assert "doctest load_settings" in args[0][0]
    assert "test_env_override_or_default" in args[0][0]
    assert "doctest load_settings" in errors[0][0]
    assert "test_a_non_string_is_refused" in errors[0][0]
    assert errors[0][0].endswith("(same callee)")
