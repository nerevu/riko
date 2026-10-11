# vim: sw=4:ts=4:expandtab
"""
Behavioral tests for the ``write`` sink beyond its doctests.

Covers sync/async parity, unwritable configurations (missing dest, invalid or
``list``/``tuple`` fmt), and the pass-through guarantee that the source
sequence survives unchanged.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest

from riko.base._paths import ROOT_DIR
from riko.modules.write import async_pipe, pipe
from riko.parsing._dotdict import DotDict
from riko.types.modules import WriteConf
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from riko.types._streams import Items

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


class TestWritePassthrough:
    """``write`` yields every input item unchanged, in order."""

    def test_sync_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS


@skipif_issync
class TestWriteParity:
    """The sync and async parsers serialize identical bytes."""

    def _read(self, path):
        with open(path, mode="rb") as f:
            return f.read()

    @pytest.mark.anyio
    async def test_json_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.json", tmp_path / "async.json"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": "json"})))
        conf = WriteConf({"dest": async_path, "fmt": "json"})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        expected = b'[{"x": 0}, {"x": 1}, {"x": 2}]'
        assert self._read(sync_path) == expected
        assert self._read(async_path) == expected

    @pytest.mark.anyio
    async def test_csv_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.csv", tmp_path / "async.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": "csv"})))
        conf = WriteConf({"dest": async_path, "fmt": "csv"})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        sync_bytes = self._read(sync_path)
        assert sync_bytes == self._read(async_path)
        assert sync_bytes.split() == [b"x", b"0", b"1", b"2"]


class TestWriteNestedItems:
    """Items holding nested mappings, as module output does, serialize to JSON."""

    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("json", b'[{"a": {"b": [1, {"c": 2}]}}]'),
            ("jsonl", b'{"a": {"b": [1, {"c": 2}]}}'),
        ],
    )
    def test_nested_dotdict_items(self, tmp_path, fmt, expected):
        items: Items = [DotDict({"a": {"b": [1, {"c": 2}]}})]
        path = tmp_path / f"out.{fmt}"
        list(pipe(items, conf=WriteConf({"dest": path, "fmt": fmt})))
        assert path.read_bytes().strip() == expected


_SEEDED_SET_WRITE = """
import sys
from riko.modules.write import pipe
items = [{"tags": {"alpha", "beta", "gamma", "delta"}}]
list(pipe(items, conf={"dest": sys.argv[1], "fmt": sys.argv[2]}))
"""


@pytest.mark.parametrize("fmt", ["json", "jsonl"])
def test_set_values_are_written_sorted_under_any_hash_seed(tmp_path, fmt):
    def write(seed: str) -> bytes:
        path = tmp_path / f"{seed}.{fmt}"
        args = [sys.executable, "-c", _SEEDED_SET_WRITE, str(path), fmt]
        env = {**os.environ, "PYTHONHASHSEED": seed}
        subprocess.run(args, check=True, cwd=ROOT_DIR, env=env)
        return path.read_bytes()

    expected = b'"tags": ["alpha", "beta", "delta", "gamma"]'
    assert all(expected in write(seed) for seed in ("1", "2", "3"))


class TestWriteSkips:
    """Unwritable configurations degrade: nothing is written, items pass through."""

    @pytest.mark.parametrize("fmt", ["bogus", "list", "tuple"])
    def test_sync_bad_target_skips_but_passes_through(self, tmp_path, fmt):
        path = tmp_path / "out"
        conf = cast("WriteConf", {"dest": path, "fmt": fmt})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS
        assert not path.exists()

    @pytest.mark.parametrize("fmt", ["bogus", "list", "tuple"])
    @async_test
    async def test_async_bad_target_skips_but_passes_through(self, tmp_path, fmt):
        path = tmp_path / "out"
        conf = WriteConf({"dest": path, "fmt": fmt})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS
        assert not path.exists()

    def test_sync_missing_dest_skips_but_passes_through(self):
        conf = cast("WriteConf", {"fmt": "json"})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_missing_dest_skips_but_passes_through(self):
        conf = cast("WriteConf", {"fmt": "json"})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS


class TestWriteTargetFromExtension:
    """When ``fmt`` is omitted, the dest extension selects the converter."""

    def _read(self, path):
        with open(path, mode="rb") as f:
            return f.read()

    def test_sync_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert self._read(path).split() == [b"x", b"0", b"1", b"2"]

    @async_test
    async def test_async_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        result = async_pipe(ITEMS, conf=WriteConf({"dest": path}))
        _ = [item async for item in result]
        assert self._read(path).split() == [b"x", b"0", b"1", b"2"]

    def test_explicit_target_overrides_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": path, "fmt": "json"})))
        assert self._read(path) == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_unknown_extension_fails(self, tmp_path, caplog):
        path = tmp_path / "out.dat"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert not path.exists()
        assert any("Invalid Formats: 'dat'" in r.message for r in caplog.records)
