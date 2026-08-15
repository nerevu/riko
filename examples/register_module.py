# vim: sw=4:ts=4:expandtab
"""
Runtime registration with **explicit** interface callables — the succinct
alternative to packaging an entry point. Define the pipe(s), then hand them to
``ModuleDefinition`` as ``sync_pipe`` / ``async_pipe`` and ``register`` it. No
``pyproject.toml``, no entry point.

The async interface is authored with the same public ``riko.ext`` decorators as
a built-in. The transform is non-blocking (does no I/O), so ``async_pipe`` reuses
the sync ``parser`` — it just needs ``isasync=True`` so it is typed as the async
interface when handed to ``ModuleDefinition``.

(For the zero-core-edit *plugin* path that other installs discover
automatically, see ``riko-example-ext/``. For the ``module=`` convention, see
``register_alias.py``.)

Run it::

    python examples/register_module.py
"""

from typing import Any, cast

from riko import AsyncPipe, SyncPipe, run
from riko.ext import ModuleDefinition, operator, register
from riko.types.configs import DynamicConf
from riko.types.general import Item, PipeTuples, Stream


def _shout(item: Item) -> Item:
    return cast(Item, {**item, "content": str(item.get("content", "")).upper()})


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: Any
) -> Stream:
    return map(_shout, stream)


# ``isasync=True`` is required here: it makes the decorated pipe the (typed)
# async interface so it can be handed to ``ModuleDefinition(async_pipe=...)``.
# (Under the ``module=`` convention the name alone suffices, see
# ``riko-example-ext``.)
@operator(isasync=True)
def async_pipe(*args: Any, **kwargs: Any) -> Stream:
    # Note: _shout is synchronous. If it performed I/O, you should create an async
    # version to perform the I/O asynchronously (e.g. httpx instead of requests) and
    # then await it here from an async_parser. E.g.:
    # `async def async_pipe(...): return await async_parser(...)`
    return parser(*args, **kwargs)


@operator()
def pipe(*args: Any, **kwargs: Any) -> Stream:
    return parser(*args, **kwargs)


register(ModuleDefinition(name="example.shout", sync_pipe=pipe, async_pipe=async_pipe))


async def main() -> None:
    # resolves by name exactly like a built-in — sync and async
    print(list(SyncPipe("example.shout", source=[{"content": "hi"}])))
    print(list(await AsyncPipe("example.shout", source=[{"content": "yo"}])))


if __name__ == "__main__":
    run(main)
