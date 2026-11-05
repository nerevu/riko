# vim: sw=4:ts=4:expandtab
"""
Provides internal tests for dependency defects that riko works around.

Each test calls the dependency directly and asserts the behavior riko needs, so it
fails until the dependency fixes the defect. A strict xfail then passes unexpectedly
and fails the run, which marks the riko workaround as ready to delete.
"""

from __future__ import annotations

from importlib.resources import files
from io import BytesIO, StringIO
from typing import TYPE_CHECKING

import pytest
from meza import convert as cv
from meza.fntools import Objectify, chunk
from meza.io import IterStringIO, Reencoder, read_csv

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet


def _reencoder_row(
    data: bytes,
    fromenc: str,
    expected: str,
    error: type[Exception],
    *,
    n: int | None = None,
    id: str,
) -> ParameterSet:
    reason = "meza's Reencoder does not decode this source correctly"
    mark = pytest.mark.xfail(strict=True, raises=error, reason=reason)
    return pytest.param(data, fromenc, n, expected, marks=mark, id=id)


_REENCODER_CASES = [
    _reencoder_row(b"hi\n", "latin-1", "hi\n", UnicodeEncodeError, id="bom-latin-1"),
    _reencoder_row(
        "a\n".encode("utf-16"), "utf-16", "a\n", UnicodeError, id="bom-utf-16"
    ),
    _reencoder_row(
        "a\nb\n".encode("utf-16-le"),
        "utf-16-le",
        "a\nb\n",
        AssertionError,
        id="utf-16-le",
    ),
    _reencoder_row(b"abcdef\n", "utf-8", "ab", AssertionError, n=2, id="read-n"),
]


class TestMeza:
    """meza behaviors that riko currently works around."""

    @pytest.mark.parametrize(("data", "fromenc", "n", "expected"), _REENCODER_CASES)
    def test_reencoder_decodes_with_bom_removal(self, data, fromenc, n, expected):
        f = BytesIO(data)
        reencoder = Reencoder(f, fromenc=fromenc, remove_BOM=True, decode=True)
        assert reencoder.read(n) == expected

    @pytest.mark.xfail(
        strict=True,
        raises=RuntimeError,
        reason="meza's read_csv raises on an empty source",
    )
    def test_read_csv_yields_nothing_for_an_empty_source(self):
        assert list(read_csv(StringIO(""))) == []

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="meza's Reencoder does not close its source",
    )
    def test_reencoder_close_closes_its_source(self):
        f = BytesIO(b"x\n")
        Reencoder(f, decode=True).close()
        assert f.closed

    @pytest.mark.xfail(
        strict=True, raises=TypeError, reason="meza's Objectify has no length"
    )
    def test_objectify_has_a_length(self):
        assert len(Objectify({"a": 1})) == 1  # pyright: ignore[reportArgumentType]

    @pytest.mark.xfail(
        strict=True,
        raises=TypeError,
        reason="meza's IterStringIO does not support the buffer protocol",
    )
    def test_iterstringio_supports_the_buffer_protocol(self):
        stream = IterStringIO(iter(["ab", "c"]))
        assert bytes(stream) == b"abc"  # pyright: ignore[reportArgumentType]

    @pytest.mark.xfail(
        strict=True, raises=AssertionError, reason="meza does not ship type information"
    )
    def test_meza_ships_type_information(self):
        assert (files("meza") / "py.typed").is_file()

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="meza's records2json writes sets in hash order",
    )
    def test_records2json_writes_sets_sorted(self):
        assert cv.records2json([{"t": {1, 8}}]).read() == '[{"t": [1, 8]}]'

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="meza's chunk splits a str into lists of characters",
    )
    def test_chunk_splits_a_str_into_strs(self):
        assert list(chunk("abcdef", 3)) == ["abc", "def"]
