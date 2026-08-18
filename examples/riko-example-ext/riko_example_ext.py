# vim: sw=4:ts=4:expandtab
"""
A minimal riko extension distribution — adds the ``example.shout`` module
(uppercases each item's ``content`` field) with **no edit to riko core**.

``shout_definition`` is what riko's registry loads; the entry point in
``pyproject.toml`` points at it. The pipe is an ordinary riko ``operator``,
authored with the same public ``riko.ext`` decorators as a built-in. The
transform is non-blocking (does no I/O), so ``async_pipe`` reuses the sync
``parser`` (``isasync`` is inferred from the ``async_pipe`` name).

Examples:
    >>> from riko import run
    >>>
    >>> next(pipe(iter([{'content': 'hi'}])))
    {'content': 'HI'}
    >>> async def main():
    ...     print(next(await async_pipe(iter([{'content': 'hi'}]))))
    >>>
    >>> run(main)
    {'content': 'HI'}

(For explicit interface callables, see ``register_module.py``. For the ``module=``
convention, see ``register_alias.py``.)

"""

import sys
from typing import Any, cast

from riko.ext import ModuleDefinition, operator
from riko.types.configs import DynamicConf
from riko.types.general import Item, PipeTuples, Stream


def _shout(item: Item) -> Item:
    return cast(Item, {**item, "content": str(item.get("content", "")).upper()})


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: Any
) -> Stream:
    return map(_shout, stream)


@operator()
def async_pipe(*args: Any, **kwargs: Any) -> Stream:
    # Note: _shout is synchronous. If it performed I/O, you should create an async
    # version to perform the I/O asynchronously (e.g. httpx instead of requests) and
    # then await it here from an async_parser. E.g.:
    # `async def async_pipe(...): return await async_parser(...)`
    return parser(*args, **kwargs)


@operator()
def pipe(*args: Any, **kwargs: Any) -> Stream:
    return parser(*args, **kwargs)


# The whole integration contract: point ``module`` at something exposing ``pipe``/
# ``async_pipe`` (here, this module). ``name`` is inferred from the entry-point key
shout_definition = ModuleDefinition(
    module=sys.modules[__name__],
    description="Uppercase the 'content' field — example riko extension module.",
)
