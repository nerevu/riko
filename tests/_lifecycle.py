# vim: sw=4:ts=4:expandtab
"""Provides the token streams, lazy embeds, and constants shared by pipeline tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.runtime._pipeline import Pipeline
from riko.runtime._workflow_pipes import workflow
from riko.types.modules import ItemBuilderConf, TokenizerRawConf

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from riko.types._streams import Item
    from riko.types._wrappers import AsyncSubPipe, SyncSubPipe

VALUE = "once is 1x,twice is 2x,thrice is 3x"

EXPECTED = [
    {"content": "once is 1x"},
    {"content": "twice is 2x"},
    {"content": "thrice is 3x"},
]

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]
LOOKAHEAD = 2
PARENTS = [{"title": "a b"}, {"title": "c d"}]
TOKENIZER_CONF = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})
HASHED = Pipeline().hash(options={"assign": "h"})


def tokenized(value: str = "a,b,c", *, hashed: bool = False) -> Pipeline:
    """Builds a token stream, one item per comma-separated part of ``value``."""
    conf = ItemBuilderConf({"attrs": {"key": "content", "value": value}})
    source = Pipeline.from_module("itembuilder", conf=conf)
    tokens = source.tokenizer(options={"emit": True})
    return tokens.hash(options={"assign": "h"}) if hashed else tokens


def gen_lazy_child(tag: str, produced: list[int], closed: list[str]) -> Generator[Item]:
    """Yields fifty ``tag``-stamped items, recording each index and ``tag`` on close."""
    try:
        for index in range(50):
            produced.append(index)
            yield {"content": f"{tag}{index}"}
    finally:
        closed.append(tag)


async def agen_lazy_child(
    tag: str, produced: list[int], closed: list[str]
) -> AsyncGenerator[Item]:
    """The async twin of ``gen_lazy_child``."""
    try:
        for index in range(50):
            produced.append(index)
            yield {"content": f"{tag}{index}"}
    finally:
        closed.append(tag)


def build_lazy_embed(produced: list[int], closed: list[str]) -> SyncSubPipe:
    """Builds a sync embed that runs ``gen_lazy_child`` on each parent's title."""

    def _sub(item, context=None, **_):
        return gen_lazy_child(str(item["title"]), produced, closed)

    return workflow()(_sub)


def build_async_lazy_embed(produced: list[int], closed: list[str]) -> AsyncSubPipe:
    """Builds an async embed that runs ``agen_lazy_child`` on each parent's title."""

    def _sub(item, context=None, **_):
        return agen_lazy_child(str(item["title"]), produced, closed)

    return workflow(is_async=True)(_sub)
