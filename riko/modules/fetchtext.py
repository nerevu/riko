# vim: sw=4:ts=4:expandtab
"""
Fetches a text file and yields one item per line.

Each line is stripped of surrounding whitespace. Unlike the other fetch pipes
this yields bare strings rather than records, so it is usually assigned to a
field or fed to a pipe that builds one.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchtext import pipe
        >>>
        >>> conf = {"url": get_path("lorem.txt")}
        >>> next(pipe(conf=conf))
        'What is Lorem Ipsum?'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._constants import ENCODING
from riko._io import Fetch, auto_close
from riko.bado.io import async_url_open
from riko.cast import BasicCastType
from riko.modules._prepare import require_conf
from riko.types._configs import FetchTextObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Item

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE, "assign": "content"}
DEFAULTS: Defaults = {"encoding": ENCODING}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: object, objconf: FetchTextObjconf, **kwargs: object
) -> Iterator[str]:
    """
    Asynchronously reads the file into a stream of stripped lines.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and `encoding`.

    Returns:
        Stripped lines. The source closes when the stream is exhausted.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path("lorem.txt")
        ...     objconf = Objectify({"url": url, "encoding": ENCODING})
        ...     result = await async_parser(None, None, objconf, assign="content")
        ...     print(next(result))
        >>>
        >>> run(main)
        What is Lorem Ipsum?

    """
    url: str = require_conf(objconf, "url", "fetchtext")
    f = await async_url_open(
        url, encoding=objconf.encoding, user_agent=objconf.user_agent
    )
    return auto_close(map(str.strip, f), f)


def parser(
    _: Item, extraction: object, objconf: FetchTextObjconf, **kwargs: object
) -> Iterator[str]:
    """
    Reads the file into a stream of stripped lines.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and `encoding`.

    Returns:
        Stripped lines. The source closes when the stream is exhausted.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path("lorem.txt")
        >>> objconf = Objectify({"url": url, "encoding": ENCODING})
        >>> result = parser(None, None, objconf, assign="content")
        >>> next(result)
        'What is Lorem Ipsum?'

    """
    url: str = require_conf(objconf, "url", "fetchtext")
    f = Fetch(url, encoding=objconf.encoding, user_agent=objconf.user_agent)
    return auto_close(map(str.strip, f), f)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[str]:
    """
    Asynchronously fetches a text file and yields lines.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The file to fetch, local or remote. Required.
            encoding (str): File encoding (default: "utf-8").
            user_agent (str): HTTP User-Agent override; unset uses riko's default.

        context (Context): the execution context

    Kwargs:
        assign (str): Field each line is assigned to. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each line directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<line>`` when ``emit`` is True (default)
        - ``{<assign>: <line>}`` when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<line>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     conf = {"url": get_path("lorem.txt")}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result))
        >>>
        >>> run(main)
        What is Lorem Ipsum?

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[str]:
    """
    Fetches a text file and yields lines.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The file to fetch, local or remote. Required.
            encoding (str): File encoding (default: "utf-8").
            user_agent (str): HTTP User-Agent override; unset uses riko's default.

        context (Context): the execution context

    Kwargs:
        assign (str): Field each line is assigned to. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each line directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<line>`` when ``emit`` is True (default)
        - ``{<assign>: <line>}`` when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<line>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {"url": get_path("lorem.txt")}
        >>> next(pipe(conf=conf))
        'What is Lorem Ipsum?'

    """
    return parser(*args, **kwargs)
