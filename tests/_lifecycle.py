# vim: sw=4:ts=4:expandtab
"""Provides the token streams and shared constants used by pipeline tests."""

from __future__ import annotations

from riko.runtime._pipeline import Pipeline
from riko.types.modules import ItemBuilderConf

VALUE = "once is 1x,twice is 2x,thrice is 3x"

EXPECTED = [
    {"content": "once is 1x"},
    {"content": "twice is 2x"},
    {"content": "thrice is 3x"},
]

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]
LOOKAHEAD = 2


def tokenized(value: str = "a,b,c", *, hashed: bool = False) -> Pipeline:
    """Builds a token stream, one item per comma-separated part of ``value``."""
    conf = ItemBuilderConf({"attrs": {"key": "content", "value": value}})
    source = Pipeline.from_module("itembuilder", conf=conf)
    tokens = source.tokenizer(options={"emit": True})
    return tokens.hash(options={"assign": "h"}) if hashed else tokens
