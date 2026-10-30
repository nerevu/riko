"""
Smoke-tests lift_constants.py on throwaway modules.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_lift_constants.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import lift_constants

SOURCE = '''\
import pytest


def helper():
    return 1


PUBLIC = 1
_PRIVATE = 2
_A, _B = 3, 4
TEXT = """
# not a comment
"""
TABLE = [pytest.param(1, id="one")]
BUILT = helper()
_PAIR = (_A, _B)


class TestThing:
    pass
'''

EXPECTED = '''\
import pytest

_PRIVATE = 2
_A, _B = 3, 4
_PAIR = (_A, _B)
PUBLIC = 1

TEXT = """
# not a comment
"""


def helper():
    return 1


BUILT = helper()

TABLE = [pytest.param(1, id="one")]


class TestThing:
    pass
'''

HELPERS = """\
import re


def _cmd():
    pass


_DEFAULT = 1
CMD = _cmd
REGISTRY: dict[str, int] = {}
REGISTRY["a"] = 1
SIZE = len(REGISTRY)


def _build(default=_DEFAULT):
    return re.compile(str(default))


PATTERN = _build(_DEFAULT)
"""

HELPERS_EXPECTED = """\
import re

_DEFAULT = 1
REGISTRY: dict[str, int] = {}


def _build(default=_DEFAULT):
    return re.compile(str(default))


PATTERN = _build(_DEFAULT)


def _cmd():
    pass


CMD = _cmd
REGISTRY["a"] = 1
SIZE = len(REGISTRY)
"""

REBOUND = """\
def f():
    pass


X = 1
X = 2
"""

GUARDED = """\
try:
    import fast
except ImportError:
    fast = None


def f():
    pass


HAS_FAST = fast is not None
"""

BRANCH = """\
import os


def f():
    pass


if os.name:
    MODE = 1
else:
    MODE = 2

LIMIT = MODE + 1
"""

OVERLOADS = """\
from typing import overload


def f():
    pass


@overload
def _inner(x: int) -> int: ...
@overload
def _inner(x: str) -> str: ...
def _inner(x):
    return x


def _outer():
    return _inner(1)


VALUE = _outer()
"""

SPACED = """\
def f():
    pass


X = 1
first = f()


second = f()
"""

REORDER = """\
PUBLIC = 1
_PRIVATE = 2
"""

RANKS = """\
from riko.base._logging import get_logger

X = 1


def f():
    pass


type Alias = int
logger = get_logger(__name__)
"""

GUARDED_EXPECTED = """\
try:
    import fast
except ImportError:
    fast = None

HAS_FAST = fast is not None


def f():
    pass
"""

BRANCH_EXPECTED = """\
import os


def f():
    pass


if os.name:
    MODE = 1
else:
    MODE = 2

LIMIT = MODE + 1
"""

OVERLOADS_EXPECTED = """\
from typing import overload


@overload
def _inner(x: int) -> int: ...
@overload
def _inner(x: str) -> str: ...
def _inner(x):
    return x


def _outer():
    return _inner(1)


VALUE = _outer()


def f():
    pass
"""

SPACED_EXPECTED = """\
X = 1


def f():
    pass


first = f()


second = f()
"""

REORDER_EXPECTED = """\
_PRIVATE = 2
PUBLIC = 1
"""

RANKS_EXPECTED = """\
from riko.base._logging import get_logger

logger = get_logger(__name__)

type Alias = int

X = 1


def f():
    pass
"""

BARE_PARAM = """\
from pytest import param


def helper():
    return 1


TABLE = [param(1, id="one")]
X = 1
"""

BARE_PARAM_EXPECTED = """\
from pytest import param

X = 1


def helper():
    return 1


TABLE = [param(1, id="one")]
"""

CASES = [
    pytest.param(
        GUARDED, GUARDED_EXPECTED, "HAS_FAST -> top", id="guarded-import-header"
    ),
    pytest.param(
        BRANCH, BRANCH_EXPECTED, "LIMIT needs MODE", id="name-bound-in-if-blocks"
    ),
    pytest.param(
        OVERLOADS, OVERLOADS_EXPECTED, "VALUE -> top", id="helpers-with-overloads"
    ),
    pytest.param(SPACED, SPACED_EXPECTED, "X -> top", id="double-blanks-kept"),
    pytest.param(REORDER, REORDER_EXPECTED, "reordered", id="reorder-only"),
    pytest.param(RANKS, RANKS_EXPECTED, "logger -> top", id="logger-then-aliases"),
    pytest.param(BARE_PARAM, BARE_PARAM_EXPECTED, "X -> top", id="bare-param-table"),
]


def _lift(tmp_path: Path, source: str) -> tuple[str, list[str]]:
    path = tmp_path / "module.py"
    path.write_text(source)
    report = lift_constants.lift(path, dry=False)
    return path.read_text(), report


def test_lifts_constants_private_first_with_helpers_before_their_user(tmp_path):
    text, _ = _lift(tmp_path, SOURCE)
    assert text == EXPECTED


def test_a_helper_follows_the_constant_it_reads_and_aliases_stay(tmp_path):
    text, report = _lift(tmp_path, HELPERS)
    assert text == HELPERS_EXPECTED
    assert [line for line in report if "needs" in line] == [
        f"{tmp_path / 'module.py'}:12 SIZE needs REGISTRY"
    ]


def test_a_second_pass_changes_nothing(tmp_path):
    text, _ = _lift(tmp_path, SOURCE)
    again, report = _lift(tmp_path, text)
    assert (again, report) == (text, [])


def test_a_rebound_name_is_reported_not_moved(tmp_path):
    text, report = _lift(tmp_path, REBOUND)
    assert text == REBOUND
    assert any("assigned more than once" in line for line in report)


@pytest.mark.parametrize(("source", "expected", "reported"), CASES)
def test_lift_cases(tmp_path, source, expected, reported):
    text, report = _lift(tmp_path, source)
    assert text == expected
    assert any(line.endswith(reported) for line in report)
