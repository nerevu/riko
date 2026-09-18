# vim: sw=4:ts=4:expandtab
"""
Uppercases each item's content field.

A minimal riko extension that adds an ``example.shout`` module. The file is authored
exactly like a built-in ``riko/modules/*.py``: ``pipe``/``async_pipe`` at module scope
with the public ``riko.ext`` decorators.

For auto registration, point an entry point at the module itself (E.g., in
``pyproject.toml`` place ``"example.shout" = "riko_example_ext"`` under
``[project.entry-points."riko.modules"]``). riko's registry reads the interface
callables and summary line from the module.

For explicit interface callables + runtime ``register``, see ``register_module.py``.
For aliasing a built-in via ``module=``, see ``register_alias.py``.

Examples:
    Install alongside riko and resolve ``example.shout`` by name::

        cd examples/riko-example-ext && uv pip install -e .
        python << 'EOF'
        from riko import SyncPipe

        source=[{'content': 'hi'}]
        print(list(SyncPipe('example.shout', source=source)))
        EOF

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from riko.ext import operator

if TYPE_CHECKING:
    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types import PipeTuples, Record, RecordStream


def _shout(item: Record) -> Record:
    return cast("Record", {**item, "content": str(item.get("content", "")).upper()})


def parser(
    stream: RecordStream, objconf: DynamicConf, tuples: PipeTuples, **kwargs: Any
) -> RecordStream:
    return map(_shout, stream)


@operator()
def async_pipe(*args: Any, **kwargs: Any) -> RecordStream:
    """
    Uppercases each item's ``content`` field.

    ``isasync=True`` is not needed here: the ``@operator()`` decorator infers the async
    interface from the ``async_pipe`` name. See ``register_module.py`` for the explicit
    ``isasync=True`` form.

    Yields:

        Each item with its ``content`` uppercased.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     print(await anext(async_pipe(iter([{"content": "hi"}]))))
        >>>
        >>> run(main)
        {'content': 'HI'}

    Notes:

        ``_shout`` is synchronous, so this reuses the sync ``parser``. If it performed
        I/O, you should create an async version (e.g. ``httpx`` instead of ``requests``)
        and await it from an ``async_parser`` here. E.g.
        ``async def async_pipe(...): return await async_parser(...)``.

    """
    return parser(*args, **kwargs)


@operator()
def pipe(*args: Any, **kwargs: Any) -> RecordStream:
    """
    Uppercases each item's ``content`` field.

    Yields:

        Each item with its ``content`` uppercased.

    Examples:

        >>> next(pipe(iter([{'content': 'hi'}])))
        {'content': 'HI'}

    """
    return parser(*args, **kwargs)
