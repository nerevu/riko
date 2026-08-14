# vim: sw=4:ts=4:expandtab
"""
A minimal extension module — uppercases the ``content`` field of each item.

It is an ordinary riko operator: authored with the same public ``riko.ext``
decorators as a built-in, so the resolved callable carries the metadata
(``pollable``/``loopable``/…) the runtime expects.

Examples:
    >>> next(pipe(iter([{'content': 'hi'}])))
    {'content': 'HI'}

"""

from typing import Any, cast

from riko.ext import operator
from riko.types.configs import DynamicConf
from riko.types.general import Item, PipeTuples, Stream


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs
) -> Stream:
    for item in stream:
        shouted = {**item, "content": str(item.get("content", "")).upper()}
        yield cast(Item, shouted)


@operator(isasync=True)
def async_pipe(*args: Any, **kwargs: Any) -> Stream:
    return parser(*args, **kwargs)


@operator()
def pipe(*args: Any, **kwargs: Any) -> Stream:
    return parser(*args, **kwargs)
