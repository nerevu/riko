# vim: sw=4:ts=4:expandtab
"""
Registers a module with **explicit** interface callables.

Assign ``ModuleDefinition``'s ``pipe`` / ``async_pipe`` kwargs to a
``SyncOperatorWrapper`` / ``AsyncOperatorWrapper``. For the packaged entry-point plugin
path, see ``riko-example-ext/``. For the ``module=`` convention, see
``register_alias.py``.

Examples:
    Run it::

        python examples/register_module.py

"""

from typing import Any, cast

from riko import AsyncPipe, SyncPipe, issync, run
from riko.ext import ModuleDefinition, operator, register
from riko.types import DynamicConf, Item, PipeTuples, Stream


def _shout(item: Item) -> Item:
    return cast(Item, {**item, "content": str(item.get("content", "")).upper()})


def parser(
    stream: Stream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: Any
) -> Stream:
    return map(_shout, stream)


@operator(isasync=True)
def async_pipe(*args: Any, **kwargs: Any) -> Stream:
    """
    Uppercases each item's ``content`` field.

    ``isasync=True`` is a static-typing requirement, not a runtime one. At runtime the
    ``async_pipe`` name alone sets ``isasync=True``, but pyright rejects assigning it
    to ``ModuleDefinition``'s ``async_pipe, because it sees ``SyncOperatorWrapper``.

    Yields:
        Each item with its ``content`` uppercased.

    Examples:
        >>> from riko import issync, run
        >>>
        >>> async def main():
        ...     print(next(await async_pipe(iter([{"content": "hi"}]))))
        >>>
        >>> print({"content": "HI"}) if issync else run(main)
        {'content': 'HI'}

    Notes:
        ``_shout`` is synchronous, so this reuses the sync ``parser``. If it performed
        I/O, you should create an async version (e.g. ``httpx`` instead of ``requests``)
        and await it from an ``async_parser`` here. E.g.
        ``async def async_pipe(...): return await async_parser(...)``.

    """
    return parser(*args, **kwargs)


@operator()
def pipe(*args: Any, **kwargs: Any) -> Stream:
    """
    Uppercases each item's ``content`` field.

    Yields:
        Each item with its ``content`` uppercased.

    Examples:
        >>> next(pipe(iter([{'content': 'hi'}])))
        {'content': 'HI'}

    """
    return parser(*args, **kwargs)


if __name__ == "__main__":
    source = [{"content": "hi"}]
    name = "example.shout"

    if issync:

        def main() -> None:
            print(list(SyncPipe(name, source=source)))

        register(ModuleDefinition(name=name, sync_pipe=pipe))
        main()

    else:

        async def amain() -> None:
            print(list(await AsyncPipe(name, source=source)))

        register(ModuleDefinition(name=name, sync_pipe=pipe, async_pipe=async_pipe))
        run(amain)
