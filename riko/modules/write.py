# vim: sw=4:ts=4:expandtab
"""
Provides functions for writing a stream to a file as a terminal sink.

``write`` is the in-pipeline counterpart of the top-level ``export`` converter:
it serializes the stream with a ``Targets`` converter and writes the result to
``conf['url']``, then yields every item unchanged so the pipeline can continue
(fan-out: write here, keep processing). Because it emits data outward it is
bucketed as a ``Sink`` in the discovery tree.

Examples:
    basic usage::

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
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from io import StringIO
from logging import Logger
from typing import Any, cast

import pygogo as gogo
from meza import io

from riko.bado.io import async_write
from riko.types.configs import WriteObjconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = Defaults({"target": "json", "mode": "wb+"})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    stream: Stream, objconf: WriteObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Asynchronously parses the pipe content

    Args:
        stream: The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf: the item independent configuration (an Objectify
            instance).

        tuples: Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs: Keyword arguments.

    Returns:
        Iter(dict): The output stream (the source items, unchanged)

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

    if not objconf.url:
        logger.warning("The url is not set, skipping writing")
    elif objconf.target in {"list", "tuple"}:
        logger.warning(f"The target {objconf.target} is not supported for writing")
    elif convert := CONVERSION_FUNCS.get(objconf.target):
        content = convert([dict(item) for item in items])

        if content is not None:
            await async_write(objconf.url, cast(StringIO, content), mode=objconf.mode)

    return iter(items)


def parser(
    stream: Stream, objconf: WriteObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Parses the pipe content

    Args:
        stream: The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf: the item independent configuration (an Objectify
            instance).

        tuples: Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs: Keyword arguments.

    Returns:
        Iter(dict): The output stream (the source items, unchanged)

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

    if not objconf.url:
        logger.warning("The url is not set, skipping writing")
    elif objconf.target in {"list", "tuple"}:
        logger.warning(f"The target {objconf.target} is not supported for writing")
    elif convert := CONVERSION_FUNCS.get(objconf.target):
        content = convert([dict(item) for item in items])

        if content is not None:
            io.write(objconf.url, content, mode=objconf.mode)

    return iter(items)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    An operator that asynchronously writes a stream to a file and passes the
    source items through unchanged.

    Args:
        items: The source.
        kwargs: The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): the destination file path
            target (str): the export format (default: 'json')
            mode (str): the file open mode (default: 'wb+')

    Returns:
        Awaitable: the source stream, unchanged

    Examples:
        >>> from riko import get_async_temp_file, run
        >>>
        >>> async def main():
        ...     async with get_async_temp_file() as fp:
        ...         conf = {"url": fp.name, "target": "csv"}
        ...         stream = await async_pipe([{"x": 0}, {"x": 1}], conf=conf)
        ...         print(next(stream))
        ...         print((await fp.read()).split())
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

    Args:
        items: The source.
        kwargs: The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): the destination file path
            target (str): the export format (default: 'json')
            mode (str): the file open mode (default: 'wb+')

    Yields:
        dict: an item

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
