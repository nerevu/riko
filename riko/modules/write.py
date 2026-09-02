# vim: sw=4:ts=4:expandtab
"""
Writes a stream to a file as a terminal sink.

``write`` is the in-pipeline counterpart of the top-level ``export`` converter:
it serializes the stream with a ``Targets`` converter and writes the result to
``conf['url']``, then yields every item unchanged so the pipeline can continue
(fan-out: write here, keep processing). Because it emits data outward it is
bucketed as a ``Sink`` in the discovery tree.

``write`` is **not lazy**. Serializing requires the complete stream, so the
source is materialized into memory before anything is written, and the
pass-through it yields replays that list rather than the original iterator. An
infinite source never reaches the write; a large one is held in full. Place it
after the pipes that shrink the stream (``filter``, ``truncate``, ``tail``),
not before.

Examples:
    Basic usage::

        >>> from riko import get_temp_file
        >>> from riko.modules.write import pipe
        >>>
        >>> with get_temp_file() as fp:
        ...     stream = pipe([{"x": 0}, {"x": 1}], conf={"url": fp.name})
        ...     next(stream)
        ...
        ...     with open(fp.name, mode="rb") as f:
        ...         f.read()
        {'x': 0}
        b'[{"x": 0}, {"x": 1}]'

Attributes:
    OPTS (Opts): The default pipe options
    DEFAULTS (Defaults): The default parser options

"""

from logging import Logger
from pathlib import Path
from typing import Any

import pygogo as gogo
from meza import io

from riko.bado.io import async_write
from riko.types._configs import WriteObjconf
from riko.types._io import IOFileLikeType
from riko.types._names import TargetLike
from riko.types._options import Defaults, Opts
from riko.types._scalars import AnyStrType
from riko.types._streams import Stream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = Defaults({"target": None, "mode": "wb+"})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _resolve_target(
    url: str | Path | None, target: TargetLike | None, *funcs: TargetLike
) -> TargetLike:
    """
    Resolves the export target from an explicit ``target``, else the url extension.

    An explicit ``target`` wins. Otherwise the url's file extension (lowercased,
    sans dot) is used when it names a known converter. This allows
    ``write(conf={"url": "out.csv"})`` to select ``csv`` as the ``target``. A url with
    no / an unknown extension falls back to ``json``.

    Args:
        url: The destination file path (a ``str``, ``Path``, or unset).
        target: The configured export format, or ``None`` to derive one.
        funcs: The known converters, keyed by target.

    Returns:
        The resolved export target.

    """
    resolved = "json"

    if target:
        resolved = target
    elif url and (ext := Path(url).suffix.lstrip(".").lower()) in funcs:
        resolved = ext

    return resolved


async def async_parser(
    stream: Stream, objconf: WriteObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Asynchronously serializes the stream and writes it to ``objconf.url``.

    Args:
        stream: The source. Note: this shares the ``tuples`` iterator, so
            consuming it will consume ``tuples`` as well.

        objconf: The item independent configuration, containing ``url``,
            ``target``, and ``mode``.

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
        ...         conf = {"url": fp.name, "target": "json", "mode": "wb+"}
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
    from riko.collections import CONVERSION_FUNCS  # noqa: PLC0415

    items = list(stream)
    target = _resolve_target(objconf.url, objconf.target, *CONVERSION_FUNCS)

    if not objconf.url:
        logger.warning("The url is not set, skipping writing")
    elif target in {"list", "tuple"}:
        logger.warning(f"The target {target} is not supported for writing")
    elif (convert := CONVERSION_FUNCS.get(target)) is None:
        logger.warning(f"The target {target} is not a known converter")
    elif (content := convert([dict(item) for item in items])) is None:
        logger.warning(f"The {target} converter produced no content")
    elif not isinstance(content, (AnyStrType, IOFileLikeType)):
        logger.warning(f"The {target} converter produced unwritable content")
    else:
        await async_write(objconf.url, content, mode=objconf.mode)

    return iter(items)


def parser(
    stream: Stream, objconf: WriteObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Serializes the stream and writes it to ``objconf.url``.

    Args:
        stream: The source. Note: this shares the ``tuples`` iterator, so
            consuming it will consume ``tuples`` as well.

        objconf: The item independent configuration, containing ``url``,
            ``target``, and ``mode``.

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
        ...     objconf = Objectify({"url": fp.name, "target": "json", "mode": "wb+"})
        ...     stream = [{"x": 0}, {"x": 1}]
        ...     tuples = zip(stream, repeat(objconf))
        ...     next(parser(stream, objconf, tuples))
        ...     fp.read()
        {'x': 0}
        b'[{"x": 0}, {"x": 1}]'

    """
    from riko.collections import CONVERSION_FUNCS  # noqa: PLC0415

    items = list(stream)
    target = _resolve_target(objconf.url, objconf.target, *CONVERSION_FUNCS)

    if not objconf.url:
        logger.warning("The url is not set, skipping writing")
    elif target in {"list", "tuple"}:
        logger.warning(f"The target {target} is not supported for writing")
    elif (convert := CONVERSION_FUNCS.get(target)) is None:
        logger.warning(f"The target {target} is not a known converter")
    elif (content := convert([dict(item) for item in items])) is None:
        logger.warning(f"The {target} converter produced no content")
    elif not isinstance(content, (AnyStrType, IOFileLikeType)):
        logger.warning(f"The {target} converter produced unwritable content")
    else:
        io.write(objconf.url, content, mode=objconf.mode)

    return iter(items)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    An operator that asynchronously writes a stream to a file and passes the
    source items through unchanged.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str | Path): the destination file path

            target (str): the export format (default: derived from the ``url``
                extension when recognized, else 'json')

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
        Nothing is written and a warning is logged when ``url`` is unset,
        ``target`` is ``'list'``/``'tuple'``, ``target`` is invalid, or the converter
        produces no content. The stream still passes through unchanged in every case.

    Examples:
        >>> from riko import get_async_temp_file, run
        >>>
        >>> async def main():
        ...     async with get_async_temp_file() as fp:
        ...         conf = {"url": fp.name, "target": "csv"}
        ...         stream = await async_pipe([{"x": 0}, {"x": 1}], conf=conf)
        ...         print(next(stream))
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
    An operator that writes a stream to a file and passes the source items
    through unchanged.

    Not lazy: materializes the source and cannot be used on an unbounded stream.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str | Path): the destination file path

            target (str): the export format (default: derived from the ``url``
                extension when recognized, else 'json')

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
        Nothing is written and a warning is logged when ``url`` is unset,
        ``target`` is ``'list'``/``'tuple'``, ``target`` is invalid, or the converter
        produces no content. The stream still passes through unchanged in every case.

    Examples:
        >>> from riko import get_temp_file
        >>>
        >>> with get_temp_file() as fp:
        ...     conf = {"url": fp.name, "target": "csv"}
        ...     stream = pipe([{"x": 0}, {"x": 1}], conf=conf)
        ...     next(stream)
        ...     fp.read().split()
        {'x': 0}
        [b'x', b'0', b'1']

    """
    return parser(*args, **kwargs)
