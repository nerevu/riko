# vim: sw=4:ts=4:expandtab
"""
Loop behavior tests.

The explicit ``loop`` operator takes the **compact** form: ``embed`` is the
sub-pipe callable, ``conf`` is the embed's own conf, and ``count``/``emit``/
``assign``/``field`` are top-level kwargs. The loop runs the embed once per parent
and folds its results against *that parent* — the Yahoo per-parent contract.

Every stream uses at least two parent items — a single parent cannot expose the
global-vs-per-parent ``count`` gap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop
from riko.modules.regex import pipe as regex
from riko.modules.strconcat import pipe as strconcat
from riko.modules.tokenizer import async_pipe as async_tok
from riko.modules.tokenizer import pipe as tokenizer
from riko.runtime._subpipe import mark_subpipe
from riko.types.modules import (
    RegexRawConf,
    RegexRawRule,
    StrconcatRawConf,
    TokenizerRawConf,
)
from tests import skipif_issync

if TYPE_CHECKING:
    from riko.runtime.context import Context
    from riko.types._streams import AsyncStream, Item, Stream
    from riko.types._wrappers import OperatorWrapperOutput

PARENTS = [{"title": "a b"}, {"title": "c d"}]
TOKENIZER_CONF = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})

LOOP_FOLD_CASES = [
    pytest.param(
        {"count": "all", "emit": True},
        [{"content": "a"}, {"content": "b"}, {"content": "c"}, {"content": "d"}],
        id="emit-all",
    ),
    pytest.param(
        {"count": "first", "emit": True},
        [{"content": "a"}, {"content": "c"}],
        id="emit-first",
    ),
    pytest.param(
        {"count": "first", "assign": "first", "emit": False},
        [
            {"title": "a b", "first": {"content": "a"}},
            {"title": "c d", "first": {"content": "c"}},
        ],
        id="assign-first",
    ),
    pytest.param(
        {"count": "all", "assign": "x", "emit": False},
        [
            {"title": "a b", "x": {"content": "a"}},
            {"title": "a b", "x": {"content": "b"}},
            {"title": "c d", "x": {"content": "c"}},
            {"title": "c d", "x": {"content": "d"}},
        ],
        id="assign-all",
    ),
]

PROCESSOR_FOLD_CASES = [
    pytest.param({"count": "first", "emit": True}, [{"content": "a"}], id="first"),
    pytest.param(
        {"count": "all", "emit": True},
        [{"content": "a"}, {"content": "b"}, {"content": "c"}],
        id="all",
    ),
    pytest.param(
        {"count": "first", "assign": "w", "emit": False},
        [{"title": "a b c", "w": {"content": "a"}}],
        id="assign-first",
    ),
]

IMPLICIT_FOLD_CASES = [
    pytest.param(
        {"emit": True},
        [{"content": "a"}, {"content": "b"}, {"content": "c"}, {"content": "d"}],
        id="all",
    ),
    pytest.param(
        {"count": "first", "emit": True},
        [{"content": "a"}, {"content": "c"}],
        id="first-per-item",
    ),
    pytest.param(
        {"count": "first", "assign": "w", "emit": False},
        [
            {"title": "a b", "w": {"content": "a"}},
            {"title": "c d", "w": {"content": "c"}},
        ],
        id="assign-first",
    ),
]

SUBPIPE_PARENTS = [{"title": "ab"}, {"title": "cd"}]
SUBPIPE_FOLD_CASES = [
    pytest.param(
        {"count": "all", "emit": True},
        [{"content": "AB"}, {"content": "ba"}, {"content": "CD"}, {"content": "dc"}],
        id="emit-all",
    ),
    pytest.param(
        {"count": "first", "emit": True},
        [{"content": "AB"}, {"content": "CD"}],
        id="emit-first",
    ),
    pytest.param(
        {"count": "first", "assign": "up", "emit": False},
        [
            {"title": "ab", "up": {"content": "AB"}},
            {"title": "cd", "up": {"content": "CD"}},
        ],
        id="assign-first",
    ),
]

ASYNC_SUBPIPE_FOLD_CASES = [SUBPIPE_FOLD_CASES[0], SUBPIPE_FOLD_CASES[2]]


async def _async_subpipe(item: Item, context: Context | None = None, **_) -> Stream:
    title = str(item.get("title", ""))
    return iter([{"content": title.upper()}, {"content": title[::-1]}])


def _sync_subpipe(item: Item, context: Context | None = None, **_) -> Stream:
    title = str(item.get("title", ""))
    return iter([{"content": title.upper()}, {"content": title[::-1]}])


_SYNC_SUBPIPE = mark_subpipe(_sync_subpipe)
_ASYNC_SUBPIPE = mark_subpipe(_async_subpipe)


def _tokenizer_loop(source: Stream, field="title", **kwargs) -> OperatorWrapperOutput:
    return loop(source, embed=tokenizer, conf=TOKENIZER_CONF, field=field, **kwargs)


class TestLoopCharacterization:
    def test_loop_maps_embed_once_per_parent(self):
        rule = RegexRawRule(
            {
                "field": {"type": "text", "value": "title"},
                "match": {"type": "text", "value": " "},
                "replace": {"type": "text", "value": "_"},
            }
        )
        result = loop(
            iter(PARENTS),
            embed=regex,
            conf=RegexRawConf({"rule": rule}),
            count="all",
            emit=True,
        )

        assert list(result) == [{"title": "a_b"}, {"title": "c_d"}]

    @pytest.mark.parametrize(("kwargs", "expected"), LOOP_FOLD_CASES)
    def test_loop_fold(self, kwargs, expected):
        result = _tokenizer_loop(iter(PARENTS), **kwargs)
        assert list(result) == expected

    def test_loop_zero_results_emit_skips_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        result = _tokenizer_loop(parents, count="all", emit=True)
        assert list(result) == [{"content": "x"}, {"content": "y"}]

    def test_loop_zero_results_assign_preserves_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        result = _tokenizer_loop(parents, count="all", assign="w", emit=False)
        assert list(result) == [
            {"title": ""},
            {"title": "x y", "w": {"content": "x"}},
            {"title": "x y", "w": {"content": "y"}},
        ]

    def test_loop_level_field_selects_child_input(self):
        parents = iter([{"title": "a b", "alt": "x y"}])
        result = _tokenizer_loop(parents, field="alt", count="all", emit=True)
        assert list(result) == [{"content": "x"}, {"content": "y"}]

    def test_loop_dynamic_conf_resolves_per_parent(self):
        parents = iter([{"title": "aa"}, {"title": "bb"}])
        conf = StrconcatRawConf(
            {
                "part": [
                    {"type": "text", "subkey": "title"},
                    {"type": "text", "value": "!"},
                ]
            }
        )
        result = loop(parents, embed=strconcat, conf=conf, count="all", emit=True)
        assert list(result) == ["aa!", "bb!"]


class TestProcessorTopLevelCount:
    """Direct processors honor first-class top-level fold kwargs."""

    @pytest.mark.parametrize(("kwargs", "expected"), PROCESSOR_FOLD_CASES)
    def test_fold(self, kwargs, expected):
        item = {"title": "a b c"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", **kwargs)
        assert list(result) == expected


class TestImplicitLooping:
    """A processor fed a stream maps itself over each item like explicit loop."""

    @pytest.mark.parametrize(("kwargs", "expected"), IMPLICIT_FOLD_CASES)
    def test_fold_per_item(self, kwargs, expected):
        result = tokenizer(iter(PARENTS), conf=TOKENIZER_CONF, field="title", **kwargs)
        assert list(result) == expected

    def test_matches_explicit_loop(self):
        implicit = tokenizer(
            iter(PARENTS), conf=TOKENIZER_CONF, field="title", count="first", emit=True
        )
        explicit = _tokenizer_loop(iter(PARENTS), count="first", emit=True)
        assert list(implicit) == list(explicit)

    def test_single_item_is_not_double_mapped(self):
        item = {"title": "a b"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", emit=True)
        assert list(result) == [{"content": "a"}, {"content": "b"}]


class TestSubpipeLoop:
    """Sub-pipelines use the same per-parent fold without sharing execution."""

    @pytest.mark.parametrize(("kwargs", "expected"), SUBPIPE_FOLD_CASES)
    def test_fold_per_parent(self, kwargs, expected):
        result = loop(iter(SUBPIPE_PARENTS), embed=_SYNC_SUBPIPE, **kwargs)
        assert list(result) == expected

    def test_count_first_is_lazy_and_closes_child(self):
        produced: list[int] = []
        closed: list[str] = []

        def child(tag: str):
            try:
                for index in range(50):
                    produced.append(index)
                    yield {"content": f"{tag}{index}"}
            finally:
                closed.append(tag)

        def _sub(item, context=None, **_):
            return child(str(item["title"]))

        parents = [{"title": "a"}, {"title": "b"}]
        result = loop(iter(parents), embed=mark_subpipe(_sub), count="first", emit=True)

        assert list(result) == [{"content": "a0"}, {"content": "b0"}]
        assert produced == [0, 0]
        assert closed == ["a", "b"]


@skipif_issync
class TestAsyncLoop:
    """Async loop preserves the sync per-parent fold and laziness contract."""

    @pytest.mark.anyio
    async def test_async_loop_matches_sync_emit(self):
        stream = async_loop(
            iter(PARENTS),
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            count="all",
            emit=True,
        )

        async_result = [item async for item in stream]
        sync_result = list(_tokenizer_loop(iter(PARENTS), count="all", emit=True))
        assert async_result == sync_result

    @pytest.mark.anyio
    async def test_async_loop_assign_per_parent(self):
        stream = async_loop(
            iter(PARENTS),
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            count="first",
            assign="first",
            emit=False,
        )
        result = [item async for item in stream]

        assert result == [
            {"title": "a b", "first": {"content": "a"}},
            {"title": "c d", "first": {"content": "c"}},
        ]

    @pytest.mark.anyio
    async def test_async_loop_is_lazy_and_ordered(self):
        consumed: list[str] = []

        def tracking() -> Stream:
            for parent in PARENTS:
                consumed.append(str(parent["title"]))
                yield parent

        stream = async_loop(
            tracking(),
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            count="all",
            emit=True,
        )

        first = await anext(cast("AsyncStream", stream))
        assert first == {"content": "a"}
        assert list(consumed) == ["a b"]


@skipif_issync
class TestAsyncSubpipeLoop:
    """Async sub-pipelines preserve the local per-parent fold contract."""

    @pytest.mark.parametrize(("kwargs", "expected"), ASYNC_SUBPIPE_FOLD_CASES)
    @pytest.mark.anyio
    async def test_fold_per_parent(self, kwargs, expected):
        stream = async_loop(iter(SUBPIPE_PARENTS), embed=_ASYNC_SUBPIPE, **kwargs)
        result = [item async for item in stream]
        assert result == expected

    @pytest.mark.anyio
    async def test_count_first_is_lazy_and_closes_child(self):
        produced: list[int] = []
        closed: list[str] = []

        def child(tag: str):
            try:
                for index in range(50):
                    produced.append(index)
                    yield {"content": f"{tag}{index}"}
            finally:
                closed.append(tag)

        async def _sub(item, context=None, **_):
            return child(str(item["title"]))

        stream = async_loop(
            iter([{"title": "a"}, {"title": "b"}]),
            embed=mark_subpipe(_sub),
            count="first",
            emit=True,
        )

        result = [item async for item in stream]
        assert result == [{"content": "a0"}, {"content": "b0"}]
        assert produced == [0, 0]
        assert closed == ["a", "b"]
