# vim: sw=4:ts=4:expandtab
"""
``isasync`` resolution for the ``processor``/``operator``/``splitter`` decorators.

``isasync`` marks *which interface* a pipe is (``pipe`` vs ``async_pipe``), not
whether the function is a coroutine — a sync ``def async_pipe`` is valid. It is
inferred from either convention signal (an ``async def``, or the ``async_pipe``
name the registry resolves), so:

- it is only *needed* explicitly for a sync callable that is the async interface
  but is not named ``async_pipe`` (e.g. a lambda), and
- a function named ``pipe`` (the sync interface) that resolves async is a
  contradiction, and raises.

The inference is ``explicit isasync`` OR ``async def`` OR name == ``async_pipe``.
The combination tables below exercise every input to that expression.
"""

from collections.abc import AsyncIterator

import pytest

from riko import run
from riko.ext import operator, processor
from riko.modules.timeout import async_pipe as timeout_async_pipe
from riko.types._streams import Item
from riko.types._wrappers import ProcessorWrapper
from tests import skipif_issync


def _create_wrapper(name: str, *, iscoro: bool, isasync: bool) -> ProcessorWrapper:
    """Decorate a fresh function with the given name/awaitability/explicit flag."""

    async def _coro(item, extraction, objconf, **kwargs) -> str:
        return str(item["content"]).upper()

    def _sync(item, extraction, objconf, **kwargs) -> str:
        return str(item["content"]).upper()

    fn = _coro if iscoro else _sync
    fn.__name__ = name
    decorate = processor(isasync=True) if isasync else processor()
    return decorate(fn)


def shout(item: Item, *args, **kwargs) -> str:
    return str(item.get("content", "")).upper()


class TestIsasyncInferenceValid:
    """Every non-contradictory combination and its resolved ``isasync``."""

    @pytest.mark.parametrize(
        ("name", "iscoro", "isasync", "expected"),
        [
            pytest.param("pipe", False, False, False, id="sync-pipe"),
            pytest.param("async_pipe", False, False, True, id="sync-async_pipe-name"),
            pytest.param("async_pipe", True, False, True, id="async_def-async_pipe"),
            pytest.param("shout", True, False, True, id="async_def-other-name"),
            pytest.param("shout", False, False, False, id="sync-other-name"),
            pytest.param("shout", False, True, True, id="explicit-required"),
            pytest.param("async_pipe", False, True, True, id="explicit-redundant-name"),
            pytest.param("shout", True, True, True, id="explicit-redundant-async"),
        ],
    )
    def test_resolved_isasync(self, name, iscoro, isasync, expected):
        assert _create_wrapper(name, iscoro=iscoro, isasync=isasync).isasync is expected


class TestExplicitIsasyncRequired:
    """
    A sync callable that is the async interface but isn't named ``async_pipe``
    (a lambda) — the only case ``isasync=True`` is required.
    """

    def test_lambda_infers_sync_without_isasync(self):
        assert processor()(shout).isasync is False

    def test_lambda_needs_explicit_isasync(self):
        assert processor(isasync=True)(shout).isasync is True

    @skipif_issync
    def test_explicit_lambda_runs_as_async_pipe(self):
        async_shout = processor(isasync=True)(shout)

        async def main():
            result = await async_shout({"content": "hi"}, assign="content")
            return list(result)

        assert run(main) == [{"content": "HI"}]


class TestInvalidCombinations:
    """A function named ``pipe`` that resolves async — always a contradiction."""

    @pytest.mark.parametrize(
        ("iscoro", "isasync"),
        [
            pytest.param(True, False, id="async_def"),
            pytest.param(False, True, id="isasync=True"),
            pytest.param(True, True, id="async_def+isasync=True"),
        ],
    )
    def test_async_named_pipe_raises(self, iscoro, isasync):
        with pytest.raises(TypeError, match="async_pipe"):
            _create_wrapper("pipe", iscoro=iscoro, isasync=isasync)

    def test_error_names_the_offending_pipe_and_reason(self):
        with pytest.raises(TypeError) as e:
            _create_wrapper("pipe", iscoro=True, isasync=False)

        message = str(e.value)
        assert "'pipe' is the synchronous interface" in message
        assert "an async def" in message

    def test_error_reason_reflects_explicit_flag(self):
        with pytest.raises(TypeError, match="marked isasync=True"):
            _create_wrapper("pipe", iscoro=False, isasync=True)


class TestAsyncGeneratorSource:
    """An async-generator (Feed) source flows through an async operator wrapper."""

    @skipif_issync
    def test_feed_source_through_timeout(self):
        async def feed():
            for x in range(3):
                yield {"x": x}

        async def main():
            result = await timeout_async_pipe(feed(), conf={})
            return list(result)

        assert run(main) == [{"x": 0}, {"x": 1}, {"x": 2}]

    @skipif_issync
    def test_feed_delivered_lazily_to_parser(self):
        received = {}

        @operator(isasync=True)
        async def async_pipe(stream, objconf, tuples, **kwargs):
            received["is_async"] = isinstance(stream, AsyncIterator)
            collected = [item async for item in stream]
            return iter(collected)

        async def feed():
            for x in range(3):
                yield {"content": x}

        async def main():
            result = await async_pipe(feed())
            return list(result)

        assert run(main) == [{"content": 0}, {"content": 1}, {"content": 2}]
        assert received["is_async"] is True
