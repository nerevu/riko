# vim: sw=4:ts=4:expandtab
"""
Tests DotDict deletion: root, nested, deep, case variation, and missing paths.
"""

import pytest

from riko.dotdict import DotDict


@pytest.mark.parametrize(
    ("source", "key", "expected"),
    [
        pytest.param(
            {"author": "bar", "title": "foo"}, "author", {"title": "foo"}, id="root"
        ),
        pytest.param(
            {"author": {"name": "bar", "url": "x.com"}},
            "author.name",
            {"author": {"url": "x.com"}},
            id="nested",
        ),
        pytest.param(
            {"a": {"b": {"c": 1, "d": 2}}}, "a.b.c", {"a": {"b": {"d": 2}}}, id="deep"
        ),
        pytest.param(
            {"author": "bar", "title": "foo"},
            "AUTHOR",
            {"title": "foo"},
            id="root-case-insensitive",
        ),
        pytest.param(
            {"author": {"name": "bar", "url": "x.com"}},
            "Author.Name",
            {"author": {"url": "x.com"}},
            id="nested-case-insensitive",
        ),
        pytest.param(
            {"a": {"b": {"c": 1, "d": 2}}},
            "A.B.C",
            {"a": {"b": {"d": 2}}},
            id="deep-case-insensitive",
        ),
        pytest.param(
            {"author": "bar"}, "missing", {"author": "bar"}, id="missing-root-noop"
        ),
        pytest.param(
            {"author": {"name": "bar"}},
            "author.missing",
            {"author": {"name": "bar"}},
            id="missing-nested-key-noop",
        ),
        pytest.param(
            {"author": {"name": "bar"}},
            "missing.name",
            {"author": {"name": "bar"}},
            id="missing-intermediate-noop",
        ),
    ],
)
def test_delete(source, key, expected):
    d = DotDict(source)
    d.delete(key)
    assert d.asdict() == expected
