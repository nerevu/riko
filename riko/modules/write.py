# vim: sw=4:ts=4:expandtab
"""
Writes a stream to a file and passes its items through unchanged.

Writing begins only after the complete source has been consumed, so the source
must be finite.

Examples:

    Basic usage::

        >>> from riko import get_temp_file
        >>> from riko.modules.write import pipe
        >>>
        >>> with get_temp_file() as fp:
        ...     stream = pipe([{"x": 0}, {"x": 1}], conf={"dest": fp.name})
        ...     next(stream)
        ...
        ...     with open(fp.name, mode="rb") as f:
        ...         f.read()
        {'x': 0}
        b'[{"x": 0}, {"x": 1}]'

Attributes:

    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pygogo as gogo
from meza import io

from riko.definitions._targets import resolve_format
from riko.io._async import async_write
from riko.io._serialization import serialize_records
from riko.types._io import IOFileLike, IOFileLikeType
from riko.types._options import Defaults, Opts
from riko.types._scalars import AnyStr, AnyStrType

from ._decorators import operator

if TYPE_CHECKING:
    from logging import Logger

    from riko.coercion._configs import WriteObjconf
    from riko.types._streams import Items, Stream
    from riko.types._wrappers import PipeTuples

OPTS: Opts = Opts()
DEFAULTS: Defaults = Defaults({"fmt": None, "mode": "wb+"})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _validate(items: Items, objconf: WriteObjconf) -> AnyStr | IOFileLike | None:
    items = list(items)
    content = None

    try:
        fmt = resolve_format(objconf.dest, objconf.fmt)
    except ValueError as e:
        logger.warning(f"{e}")
    else:
        if not objconf.dest:
            logger.warning("The destination is not set. Skipping writing.")
        elif (content := serialize_records(items, fmt)) is None:
            logger.warning(f"The {fmt} converter produced no content")
        elif not isinstance(content, (AnyStrType, IOFileLikeType)):
            logger.warning(f"The {fmt} converter produced unwritable content")

    return cast("AnyStr | IOFileLike", content)


async def async_parser(
    stream: Stream, objconf: WriteObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Asynchronously serializes the stream and writes it to ``objconf.dest``.

    Args:

        stream: The source. Note: this shares the ``tuples`` iterator, so
            consuming it will consume ``tuples`` as well.

        objconf: The item independent configuration: ``dest``, ``fmt``, and ``mode``.

        tuples: Iterable of ``(item, objconf)`` pairs, where ``item`` is an
            element in the source stream. Note: this shares the ``stream``
            iterator, so consuming it will consume ``stream`` as well.

    Returns:

        The original stream.

    Examples:

        >>> from itertools import repeat
        >>> from meza.fntools import Objectify
        >>> from riko import get_async_temp_file, run
        >>>
        >>> async def main():
        ...     async with get_async_temp_file() as fp:
        ...         conf = {"dest": fp.name, "fmt": "json", "mode": "wb+"}
        ...         objconf = Objectify(conf)
        ...         stream = [{"x": 0}, {"x": 1}]
        ...         tuples = zip(stream, repeat(objconf))
        ...         result = await async_parser(stream, objconf, tuples)
        ...         print(next(result))
        ...         print(await fp.read())
        >>>
        >>> run(main)
        {'x': 0}
        b'[{"x": 0}, {"x": 1}]'

    """
    items = list(stream)

    if content := _validate(items, objconf):
        await async_write(objconf.dest, content, mode=objconf.mode)

    return iter(items)


def parser(
    stream: Stream, objconf: WriteObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Serializes the stream and writes it to ``objconf.dest``.

    Args:

        stream: The source. Note: this shares the ``tuples`` iterator, so
            consuming it will consume ``tuples`` as well.

        objconf: The item independent configuration: ``dest``, ``fmt``, and ``mode``.

        tuples: Iterable of ``(item, objconf)`` pairs, where ``item`` is an
            element in the source stream. Note: this shares the ``stream``
            iterator, so consuming it will consume ``stream`` as well.

    Returns:

        The original stream.

    Examples:

        >>> from itertools import repeat
        >>> from meza.fntools import Objectify
        >>> from riko import get_temp_file
        >>>
        >>> with get_temp_file() as fp:
        ...     objconf = Objectify({"dest": fp.name, "fmt": "json", "mode": "wb+"})
        ...     stream = [{"x": 0}, {"x": 1}]
        ...     tuples = zip(stream, repeat(objconf))
        ...     next(parser(stream, objconf, tuples))
        ...     fp.read()
        {'x': 0}
        b'[{"x": 0}, {"x": 1}]'

    """
    items = list(stream)

    if content := _validate(items, objconf):
        io.write(objconf.dest, content, mode=objconf.mode)

    return iter(items)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Write an async stream to a file and pass its items through unchanged.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:

        items (Items): The source stream.

        conf (dict): The pipe configuration. Must contain the key 'dest'.

            dest (PathLike): the destination file path

            fmt (str): the export format (default: derived from the ``dest`` extension
                when recognized, else 'json')

            mode (str): the file open mode (default: 'wb+')

        context (Context): the execution context

    Kwargs:

        assign (str): Field the output stream is assigned to. Ignored when ``emit`` is
            True (default: "write").

        emit (bool): Whether to emit the output stream directly rather than assigning
            it. Overrides ``assign`` (default: True).

    Yields:

        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Notes:

        Nothing is written and a warning is logged when ``dest`` is unset,
        ``fmt`` is ``'list'``/``'tuple'``, ``fmt`` is invalid, or the converter
        produces no content. The stream still passes through unchanged in every case.

    Examples:

        >>> from riko import get_async_temp_file, run
        >>>
        >>> async def main():
        ...     async with get_async_temp_file() as fp:
        ...         conf = {"dest": fp.name, "fmt": "csv"}
        ...         stream = async_pipe([{"x": 0}, {"x": 1}], conf=conf)
        ...         print(await anext(stream))
        ...         print((await fp.read()).split())
        >>>
        >>> run(main)
        {'x': 0}
        [b'x', b'0', b'1']

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Write a stream to a file and pass its items through unchanged.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:

        items (Items): The source stream.

        conf (dict): The pipe configuration. Must contain the key 'dest'.

            dest (PathLike): the destination file path

            fmt (str): the export format (default: derived from the ``dest`` extension
                when recognized, else 'json')

            mode (str): the file open mode (default: 'wb+')

        context (Context): the execution context

    Kwargs:

        assign (str): Field the output stream is assigned to. Ignored when ``emit`` is
            True (default: "write").

        emit (bool): Whether to emit the output stream directly rather than assigning
            it. Overrides ``assign`` (default: True).

    Yields:

        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Notes:

        Nothing is written and a warning is logged when ``dest`` is unset,
        ``fmt`` is ``'list'``/``'tuple'``, ``fmt`` is invalid, or the converter
        produces no content. The stream still passes through unchanged in every case.

    Examples:

        >>> from riko import get_temp_file
        >>>
        >>> with get_temp_file() as fp:
        ...     conf = {"dest": fp.name, "fmt": "csv"}
        ...     stream = pipe([{"x": 0}, {"x": 1}], conf=conf)
        ...     next(stream)
        ...     fp.read().split()
        {'x': 0}
        [b'x', b'0', b'1']

    """
    return parser(*args, **kwargs)
