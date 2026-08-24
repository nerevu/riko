# vim: sw=4:ts=4:expandtab
"""
Tests pipe implementations.
"""

from itertools import count
from typing import Any

import pytest

from riko.cast import SortableCastType
from riko.modules.join import pipe as join_pipe
from riko.modules.sort import pipe as sort_pipe
from riko.types.modules import JoinConf, SortConf, SortConfRule


def _values(stream: Any, key: str) -> list[Any]:
    return [item.get(key) for item in stream]


_LOOKAHEAD = 2


def _counting_source(consumed: list[int]) -> Any:
    for i in count():
        consumed.append(i)
        yield {"x": "foo", "i": i}


@pytest.mark.parametrize(
    ("dir_", "type_", "vals"),
    [
        ("asc", SortableCastType.FLOAT, ["1", "2", "3"]),
        ("asc", SortableCastType.DECIMAL, ["1", "2", "3"]),
        ("asc", SortableCastType.DATE, ["2019-01-01", "2020-05-01", "2024-11-12"]),
        ("asc", SortableCastType.DATETIME, ["2019-01-01", "2020-05-01", "2024-11-12"]),
        ("desc", SortableCastType.FLOAT, ["1", "2", "3"]),
        ("desc", SortableCastType.DECIMAL, ["1", "2", "3"]),
        ("desc", SortableCastType.DATE, ["2019-01-01", "2020-05-01", "2024-11-12"]),
        ("desc", SortableCastType.DATETIME, ["2019-01-01", "2020-05-01", "2024-11-12"]),
    ],
)
def test_sort_fillers_stay_orderable(dir_, type_, vals: list[str]):
    """
    A missing or unparseable numeric field must not poison the sort with NaN.
    """
    rule = SortConfRule(field="n", dir=dir_, type=type_)
    conf = SortConf(rule=rule)

    if dir_ == "asc":
        expected_mid = [None, "abc", *vals]
        expected_first = ["abc", None, *vals]
    else:
        expected_mid = [*reversed(vals), None, "abc"]
        expected_first = [*reversed(vals), "abc", None]

    mid = [{"n": vals[2]}, {"x": "abc"}, {"n": "abc"}, {"n": vals[0]}, {"n": vals[1]}]
    first = [{"n": "abc"}, {"x": "abc"}, {"n": vals[2]}, {"n": vals[0]}, {"n": vals[1]}]

    assert _values(sort_pipe(mid, conf=conf), "n") == expected_mid
    assert _values(sort_pipe(first, conf=conf), "n") == expected_first


def test_keyed_join_does_not_materialize_its_primary():
    """
    ``other`` is the replayed side, so an unbounded primary must still emit.
    """
    consumed: list[int] = []
    other = [{"x": "bar", "c": 4}, {"x": "foo", "c": 5}]
    conf = JoinConf(join_key="x")
    joined = join_pipe(_counting_source(consumed), conf=conf, other=other)

    assert next(joined) == {"x": "foo", "i": 0, "c": 5}
    assert len(consumed) <= _LOOKAHEAD
    assert next(joined) == {"x": "foo", "i": 1, "c": 5}
    assert len(consumed) <= 1 + _LOOKAHEAD


def test_natural_join_does_not_materialize_its_primary():
    """
    The keyless natural join is lazy in its primary stream too.
    """
    consumed: list[int] = []
    joined = join_pipe(_counting_source(consumed), other=[{"c": 5}])

    assert next(joined) == {"x": "foo", "i": 0, "c": 5}
    assert len(consumed) <= _LOOKAHEAD
