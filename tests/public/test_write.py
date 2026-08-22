# vim: sw=4:ts=4:expandtab
"""
Behavioral tests for the ``write`` sink beyond its doctests.

Covers sync/async parity, unwritable configurations (missing url, invalid or
``list``/``tuple`` target), and the pass-through guarantee that the source
sequence survives unchanged.
"""

import pytest

from riko.bado import isasync, run
from riko.modules.write import async_pipe, pipe

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


def _run_async_pipe(items, conf):
    captured = []

    async def main():
        stream = await async_pipe(items, conf=conf)
        captured.extend(stream)

    run(main)
    return captured


class TestWritePassthrough:
    """``write`` yields every source item unchanged, in order."""

    def test_sync_preserves_sequence(self, tmp_path):
        conf = {"url": str(tmp_path / "out.json")}
        assert list(pipe(list(ITEMS), conf=conf)) == ITEMS

    @pytest.mark.skipif(not isasync, reason="anyio not installed")
    def test_async_preserves_sequence(self, tmp_path):
        conf = {"url": str(tmp_path / "out.json")}
        assert _run_async_pipe(list(ITEMS), conf=conf) == ITEMS


@pytest.mark.skipif(not isasync, reason="anyio not installed")
class TestWriteParity:
    """The sync and async parsers serialize identical bytes."""

    def _read(self, path):
        with open(path, mode="rb") as f:
            return f.read()

    @pytest.mark.skipif(not isasync, reason="anyio not installed")
    def test_json_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.json", tmp_path / "async.json"
        list(pipe(list(ITEMS), conf={"url": str(sync_path), "target": "json"}))
        _run_async_pipe(list(ITEMS), conf={"url": str(async_path), "target": "json"})
        expected = b'[{"x": 0}, {"x": 1}, {"x": 2}]'
        assert self._read(sync_path) == expected
        assert self._read(async_path) == expected

    @pytest.mark.skipif(not isasync, reason="anyio not installed")
    def test_csv_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.csv", tmp_path / "async.csv"
        list(pipe(list(ITEMS), conf={"url": str(sync_path), "target": "csv"}))
        _run_async_pipe(list(ITEMS), conf={"url": str(async_path), "target": "csv"})
        sync_bytes = self._read(sync_path)
        assert sync_bytes == self._read(async_path)
        assert sync_bytes.split() == [b"x", b"0", b"1", b"2"]


class TestWriteSkips:
    """Unwritable configurations degrade: nothing is written, items pass through."""

    @pytest.mark.parametrize(
        "target", ["bogus", "list", "tuple"], ids=["invalid", "list", "tuple"]
    )
    def test_sync_bad_target_skips_but_passes_through(self, tmp_path, target):
        path = tmp_path / "out"
        conf = {"url": str(path), "target": target}
        assert list(pipe(list(ITEMS), conf=conf)) == ITEMS
        assert not path.exists()

    @pytest.mark.parametrize(
        "target", ["bogus", "list", "tuple"], ids=["invalid", "list", "tuple"]
    )
    @pytest.mark.skipif(not isasync, reason="anyio not installed")
    def test_async_bad_target_skips_but_passes_through(self, tmp_path, target):
        path = tmp_path / "out"
        conf = {"url": str(path), "target": target}
        assert _run_async_pipe(list(ITEMS), conf=conf) == ITEMS
        assert not path.exists()

    def test_sync_missing_url_skips_but_passes_through(self):
        assert list(pipe(list(ITEMS), conf={"target": "json"})) == ITEMS

    @pytest.mark.skipif(not isasync, reason="anyio not installed")
    def test_async_missing_url_skips_but_passes_through(self):
        assert _run_async_pipe(list(ITEMS), conf={"target": "json"}) == ITEMS
