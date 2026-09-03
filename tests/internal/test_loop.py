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

from typing import cast

import pytest

from riko.context import Context
from riko.modules._subpipe import mark_subpipe
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop
from riko.modules.regex import pipe as regex
from riko.modules.strconcat import pipe as strconcat
from riko.modules.tokenizer import async_pipe as async_tok
from riko.modules.tokenizer import pipe as tokenizer
from riko.types._streams import AsyncStream, Item, Stream
from riko.types._wrappers import OperatorWrapperOutput
from riko.types.modules import (
    RegexRawConf,
    RegexRawRule,
    StrconcatRawConf,
    TokenizerRawConf,
)
from tests import skipif_issync

PARENTS = [{"title": "a b"}, {"title": "c d"}]
TOKENIZER_CONF = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})


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

    def test_loop_count_all_flattens_embedded_results(self):
        result = _tokenizer_loop(iter(PARENTS), count="all", emit=True)
        assert list(result) == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]

    def test_loop_count_first_per_parent(self):
        # count="first" keeps the first result *per parent*.
        result = _tokenizer_loop(iter(PARENTS), count="first", emit=True)
        assert list(result) == [{"content": "a"}, {"content": "c"}]

    def test_loop_assign_count_first_preserves_parent(self):
        # The first result per parent is assigned onto the preserved parent.
        result = _tokenizer_loop(
            iter(PARENTS), count="first", assign="first", emit=False
        )

        assert list(result) == [
            {"title": "a b", "first": {"content": "a"}},
            {"title": "c d", "first": {"content": "c"}},
        ]

    def test_loop_assign_count_all_preserves_parent(self):
        # One preserved-parent copy per child result.
        result = _tokenizer_loop(iter(PARENTS), count="all", assign="x", emit=False)

        assert list(result) == [
            {"title": "a b", "x": {"content": "a"}},
            {"title": "a b", "x": {"content": "b"}},
            {"title": "c d", "x": {"content": "c"}},
            {"title": "c d", "x": {"content": "d"}},
        ]

    def test_loop_zero_results_emit_skips_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        # A parent with no child results emits nothing (emit mode).
        result = _tokenizer_loop(parents, count="all", emit=True)
        assert list(result) == [{"content": "x"}, {"content": "y"}]

    def test_loop_zero_results_assign_preserves_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        # A parent with no child results is yielded unchanged once.
        result = _tokenizer_loop(parents, count="all", assign="w", emit=False)
        assert list(result) == [
            {"title": ""},
            {"title": "x y", "w": {"content": "x"}},
            {"title": "x y", "w": {"content": "y"}},
        ]

    def test_loop_level_field_selects_child_input(self):
        # Loop-level `field` chooses which parent field feeds the embed: the
        # tokenizer sees parent["alt"], not parent["title"].
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
    """
    A direct processor node honors a first-class top-level ``count`` kwarg —
    the runtime enabler for compact-form processor-loop migration.
    """

    def test_count_first_keeps_first(self):
        item = {"title": "a b c"}
        result = tokenizer(
            item, conf=TOKENIZER_CONF, field="title", count="first", emit=True
        )
        assert list(result) == [{"content": "a"}]

    def test_count_all_keeps_all(self):
        item = {"title": "a b c"}
        result = tokenizer(
            item, conf=TOKENIZER_CONF, field="title", count="all", emit=True
        )
        assert list(result) == [{"content": "a"}, {"content": "b"}, {"content": "c"}]

    def test_count_first_assign_preserves_item(self):
        item = {"title": "a b c"}
        result = tokenizer(
            item,
            conf=TOKENIZER_CONF,
            field="title",
            count="first",
            assign="w",
            emit=False,
        )
        assert list(result) == [{"title": "a b c", "w": {"content": "a"}}]


class TestImplicitLooping:
    """
    A processor fed a *stream* maps itself over each item, exactly like
    ``loop(source, embed=<processor>)``.
    """

    def test_maps_over_every_item(self):
        stream = iter([{"title": "a b"}, {"title": "c d"}])
        result = tokenizer(stream, conf=TOKENIZER_CONF, field="title", emit=True)
        assert list(result) == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]

    def test_count_first_is_per_item(self):
        stream = iter([{"title": "a b"}, {"title": "c d"}])
        result = tokenizer(
            stream, conf=TOKENIZER_CONF, field="title", count="first", emit=True
        )
        assert list(result) == [{"content": "a"}, {"content": "c"}]

    def test_assign_folds_onto_each_item(self):
        stream = iter([{"title": "a b"}, {"title": "c d"}])
        result = tokenizer(
            stream,
            conf=TOKENIZER_CONF,
            field="title",
            count="first",
            assign="w",
            emit=False,
        )
        assert list(result) == [
            {"title": "a b", "w": {"content": "a"}},
            {"title": "c d", "w": {"content": "c"}},
        ]

    def test_matches_explicit_loop(self):
        parents = [{"title": "a b"}, {"title": "c d"}]
        implicit = tokenizer(
            iter(parents), conf=TOKENIZER_CONF, field="title", count="first", emit=True
        )
        explicit = _tokenizer_loop(iter(parents), count="first", emit=True)
        assert list(implicit) == list(explicit)

    def test_single_item_is_not_double_mapped(self):
        # a loop passes single items to the embedder; the single-item path applies
        item = {"title": "a b"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", emit=True)
        assert list(result) == [{"content": "a"}, {"content": "b"}]


class TestSubpipeLoop:
    """
    A loop may embed a *sub-pipeline* — a compiled ``pipe_*`` callable with no
    ``type``/``loopable`` attrs. It runs once per parent (like a loopable
    processor), and the loop applies the same per-parent ``count``/``emit``/
    ``assign`` fold to its output stream.
    """

    def test_emit_all_flattens_per_parent(self):
        parents = [{"title": "ab"}, {"title": "cd"}]
        result = loop(iter(parents), embed=_SYNC_SUBPIPE, count="all", emit=True)
        assert list(result) == [
            {"content": "AB"},
            {"content": "ba"},
            {"content": "CD"},
            {"content": "dc"},
        ]

    def test_emit_first_keeps_first_per_parent(self):
        parents = [{"title": "ab"}, {"title": "cd"}]
        result = loop(iter(parents), embed=_SYNC_SUBPIPE, count="first", emit=True)
        assert list(result) == [{"content": "AB"}, {"content": "CD"}]

    def test_assign_folds_first_onto_parent(self):
        parents = [{"title": "ab"}, {"title": "cd"}]
        result = loop(
            iter(parents), embed=_SYNC_SUBPIPE, count="first", assign="up", emit=False
        )
        assert list(result) == [
            {"title": "ab", "up": {"content": "AB"}},
            {"title": "cd", "up": {"content": "CD"}},
        ]

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
    """
    The lazy-async loop (``async_pipe``) runs the embed once per parent
    *sequentially* and yields an ``AsyncIterator``, applying the same per-parent
    fold as the sync loop (Phase 3 parity).
    """

    @pytest.mark.anyio
    async def test_async_loop_matches_sync_emit(self):
        stream = await async_loop(
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
        stream = await async_loop(
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

        stream = await async_loop(
            tracking(),
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            count="all",
            emit=True,
        )

        first = await anext(cast(AsyncStream, stream))
        assert first == {"content": "a"}
        assert list(consumed) == ["a b"]


@skipif_issync
class TestAsyncSubpipeLoop:
    """
    The lazy-async loop may embed an *async* sub-pipeline (``AsyncSubPipe``): it
    runs once per parent (sequentially) and applies the per-parent fold.
    """

    @pytest.mark.anyio
    async def test_emit_all_flattens_per_parent(self):
        stream = await async_loop(
            iter([{"title": "ab"}, {"title": "cd"}]),
            embed=_ASYNC_SUBPIPE,
            count="all",
            emit=True,
        )
        result = [item async for item in stream]

        assert result == [
            {"content": "AB"},
            {"content": "ba"},
            {"content": "CD"},
            {"content": "dc"},
        ]

    @pytest.mark.anyio
    async def test_assign_folds_first_onto_parent(self):
        stream = await async_loop(
            iter([{"title": "ab"}, {"title": "cd"}]),
            embed=_ASYNC_SUBPIPE,
            count="first",
            assign="up",
            emit=False,
        )
        result = [item async for item in stream]

        assert result == [
            {"title": "ab", "up": {"content": "AB"}},
            {"title": "cd", "up": {"content": "CD"}},
        ]

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

        stream = await async_loop(
            iter([{"title": "a"}, {"title": "b"}]),
            embed=mark_subpipe(_sub),
            count="first",
            emit=True,
        )

        result = [item async for item in stream]
        assert result == [{"content": "a0"}, {"content": "b0"}]
        assert produced == [0, 0]
        assert closed == ["a", "b"]
