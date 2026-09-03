# vim: sw=4:ts=4:expandtab
"""
Behavioral tests for the ``write`` sink beyond its doctests.

Covers sync/async parity, unwritable configurations (missing url, invalid or
``list``/``tuple`` target), and the pass-through guarantee that the source
sequence survives unchanged.
"""

from typing import cast

import pytest

from riko.modules.write import async_pipe, pipe
from riko.types.modules import WriteConf
from tests import async_test, skipif_issync

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


class TestWritePassthrough:
    """``write`` yields every source item unchanged, in order."""

    def test_sync_preserves_sequence(self, tmp_path):
        conf = WriteConf({"url": str(tmp_path / "out.json")})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_preserves_sequence(self, tmp_path):
        conf = WriteConf({"url": str(tmp_path / "out.json")})
        result = await async_pipe(ITEMS, conf=conf)
        assert list(result) == ITEMS


@skipif_issync
class TestWriteParity:
    """The sync and async parsers serialize identical bytes."""

    def _read(self, path):
        with open(path, mode="rb") as f:
            return f.read()

    @pytest.mark.anyio
    async def test_json_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.json", tmp_path / "async.json"
        list(pipe(ITEMS, conf=WriteConf({"url": sync_path, "target": "json"})))
        await async_pipe(ITEMS, conf=WriteConf({"url": async_path, "target": "json"}))
        expected = b'[{"x": 0}, {"x": 1}, {"x": 2}]'
        assert self._read(sync_path) == expected
        assert self._read(async_path) == expected

    @pytest.mark.anyio
    async def test_csv_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.csv", tmp_path / "async.csv"
        list(pipe(ITEMS, conf=WriteConf({"url": sync_path, "target": "csv"})))
        await async_pipe(ITEMS, conf=WriteConf({"url": async_path, "target": "csv"}))
        sync_bytes = self._read(sync_path)
        assert sync_bytes == self._read(async_path)
        assert sync_bytes.split() == [b"x", b"0", b"1", b"2"]


class TestWriteSkips:
    """Unwritable configurations degrade: nothing is written, items pass through."""

    @pytest.mark.parametrize("target", ["bogus", "list", "tuple"])
    def test_sync_bad_target_skips_but_passes_through(self, tmp_path, target):
        path = tmp_path / "out"
        conf = cast(WriteConf, {"url": path, "target": target})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS
        assert not path.exists()

    @pytest.mark.parametrize("target", ["bogus", "list", "tuple"])
    @async_test
    async def test_async_bad_target_skips_but_passes_through(self, tmp_path, target):
        path = tmp_path / "out"
        conf = WriteConf({"url": str(path), "target": target})
        result = await async_pipe(ITEMS, conf=conf)
        assert list(result) == ITEMS
        assert not path.exists()

    def test_sync_missing_url_skips_but_passes_through(self):
        conf = cast(WriteConf, {"target": "json"})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_missing_url_skips_but_passes_through(self):
        conf = cast(WriteConf, {"target": "json"})
        result = await async_pipe(ITEMS, conf=conf)
        assert list(result) == ITEMS


class TestWriteTargetFromExtension:
    """When ``target`` is omitted, the url extension selects the converter."""

    def _read(self, path):
        with open(path, mode="rb") as f:
            return f.read()

    def test_sync_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"url": path})))
        assert self._read(path).split() == [b"x", b"0", b"1", b"2"]

    @async_test
    async def test_async_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        await async_pipe(ITEMS, conf=WriteConf({"url": str(path)}))
        assert self._read(path).split() == [b"x", b"0", b"1", b"2"]

    def test_explicit_target_overrides_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"url": path, "target": "json"})))
        assert self._read(path) == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_unknown_extension_falls_back_to_json(self, tmp_path):
        path = tmp_path / "out.dat"
        list(pipe(ITEMS, conf=WriteConf({"url": path})))
        assert self._read(path) == b'[{"x": 0}, {"x": 1}, {"x": 2}]'
