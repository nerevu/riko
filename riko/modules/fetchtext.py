# vim: sw=4:ts=4:expandtab
"""
Fetches a text file and yields one item per line.

Each line is stripped of surrounding whitespace. Unlike the other fetch modules
this yields bare strings rather than items, so it is usually assigned to a
field or fed to a module that builds one.

Examples:

    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchtext import pipe
        >>>
        >>> conf = {"url": get_path("lorem.txt")}
        >>> next(pipe(conf=conf))
        'What is Lorem Ipsum?'

Attributes:

    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from riko.base._config import ENCODING
from riko.base._logging import get_logger
from riko.base._require_guards import require_conf_key
from riko.io._async import async_url_open
from riko.io._reencode import gen_without_bom
from riko.io._sync import Fetch, auto_close
from riko.types._enums import BasicCastType

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from logging import Logger

    from riko.coercion._configs import FetchTextObjconf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._streams import Item

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = {"ftype": BasicCastType.NONE, "assign": "content"}
DEFAULTS: Defaults = {"encoding": ENCODING, "strip_bom": True}


def _gen_stripped_lines(lines: Iterable[str], strip_bom: bool) -> Iterator[str]:
    """
    Generates each line stripped of surrounding whitespace and, optionally, a BOM.

    Examples:

        >>> list(_gen_stripped_lines(["\\ufeffhi\\n", "there\\n"], True))
        ['hi', 'there']

    """
    yield from map(str.strip, gen_without_bom(lines) if strip_bom else lines)


async def async_parser(
    _: Item, extraction: object, objconf: FetchTextObjconf, **kwargs: object
) -> Iterator[str]:
    """
    Asynchronously reads the file into a stream of stripped lines.

    Args:

        _: The item. Unused.

        extraction: The extracted conf value. Unused.

        objconf: The module configuration: `url`, `encoding`, `strip_bom`, and
            `user_agent`.

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
        ...     conf = {"url": url, "encoding": ENCODING, "strip_bom": True}
        ...     objconf = Objectify(conf)
        ...     result = await async_parser(None, None, objconf, assign="content")
        ...     print(next(result))
        >>>
        >>> run(main)
        What is Lorem Ipsum?

    """
    url: str = require_conf_key(objconf, "url", "fetchtext", strict=True)
    f = await async_url_open(
        url, encoding=objconf.encoding, user_agent=objconf.user_agent
    )
    return auto_close(_gen_stripped_lines(f, objconf.strip_bom), f)


def parser(
    _: Item, extraction: object, objconf: FetchTextObjconf, **kwargs: object
) -> Iterator[str]:
    """
    Reads the file into a stream of stripped lines.

    Args:

        _: The item. Unused.

        extraction: The extracted conf value. Unused.

        objconf: The module configuration: `url`, `encoding`, `strip_bom`, and
            `user_agent`.

    Returns:

        Stripped lines. The source closes when the stream is exhausted.

    Raises:

        TypeError: If ``conf`` has no ``url`` key.

    Examples:

        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path("lorem.txt")
        >>> conf = {"url": url, "encoding": ENCODING, "strip_bom": True}
        >>> objconf = Objectify(conf)
        >>> result = parser(None, None, objconf, assign="content")
        >>> next(result)
        'What is Lorem Ipsum?'

    """
    url: str = require_conf_key(objconf, "url", "fetchtext", strict=True)
    f = Fetch(url, encoding=objconf.encoding, user_agent=objconf.user_agent)
    return auto_close(_gen_stripped_lines(f, objconf.strip_bom), f)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[str]:
    """
    Asynchronously fetches a text file and yields lines.

    Args:

        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The module configuration.

            url (str): The file to fetch, local or remote. Required.

            encoding (str): File encoding (default: "utf-8").

            strip_bom (bool): Whether to remove a byte order mark (BOM) from the first
                line (default: True).

            user_agent (str): HTTP ``User-Agent`` to send. ``UserAgent.DESKTOP``,
                ``MOBILE``, or ``RANDOM`` pick a common browser agent of that kind per
                request (default: "riko/<version>").

        context (Context): the run environment

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
        ...     result = async_pipe(conf=conf)
        ...     print(await anext(result))
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

        conf (dict): The module configuration.

            url (str): The file to fetch, local or remote. Required.

            encoding (str): File encoding (default: "utf-8").

            strip_bom (bool): Whether to remove a byte order mark (BOM) from the first
                line (default: True).

            user_agent (str): HTTP ``User-Agent`` to send. ``UserAgent.DESKTOP``,
                ``MOBILE``, or ``RANDOM`` pick a common browser agent of that kind per
                request (default: "riko/<version>").

        context (Context): the run environment

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
        >>> next(pipe(conf=conf, assign="line", emit=False))
        {'line': 'What is Lorem Ipsum?'}

    """
    return parser(*args, **kwargs)
