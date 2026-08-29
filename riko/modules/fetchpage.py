# vim: sw=4:ts=4:expandtab
"""
Fetches a web page as a string.

Slices the page between ``start`` and ``end``, optionally strips its html tags,
and optionally splits it on a ``token``. Yields bare strings rather than
records, so the result is usually assigned to a field or fed to the regex
module.

Examples:
    Basic usage::

        >>> from riko.modules.fetchpage import pipe
        >>> from riko import get_path
        >>>
        >>> url = get_path("cnn.html")
        >>> conf = {"url": url, "start": "<title>", "end": "</title>"}
        >>> next(pipe(conf=conf))[:21]
        'CNN.com International'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any

import pygogo as gogo

from riko import ENCODING
from riko._io import Fetch
from riko._iterutils import betwix
from riko.bado import io
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.parsers import get_text
from riko.types._configs import FetchPageObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Item

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = Defaults({"encoding": ENCODING, "detag": False})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def get_string(content: str, start: str, end: str) -> str:
    # TODO: convert relative links to absolute
    # TODO: remove the closing tag if using an HTML tag stripped of HTML tags
    # TODO: clean html with Tidy
    start_pos = content.find(start) if start else 0
    right = content[start_pos + (len(start) if start else 0) :]
    end_pos = right[1:].find(end) + 1 if end else len(right)
    return right[:end_pos] if end_pos > 0 else right


async def async_parser(
    _: Item, extraction: object, objconf: FetchPageObjconf, **kwargs: object
) -> Iterator[str]:
    """
    Asynchronously fetches the page and returns the requested slice.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `start`, `end`, `token` and
            `detag`.

    Returns:
        One string, or one per ``token`` separated piece. Each is stripped of
        surrounding whitespace.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path("cnn.html")
        ...     conf = {"url": url, "start": "<title>", "end": "</title>"}
        ...     objconf = Objectify(conf)
        ...     kwargs = {"stream": {}, "assign": "content"}
        ...     result = await async_parser(None, None, objconf, **kwargs)
        ...     print(next(result)[:32])
        >>>
        >>> run(main)
        CNN.com International - Breaking

    """
    url: str = require_conf(objconf, "url", "fetchpage")
    content = await io.async_url_read(url)
    parsed = get_string(content, objconf.start or "", objconf.end or "")
    detagged = get_text(parsed) if objconf.detag else parsed
    split = detagged.split(objconf.token) if objconf.token else [detagged]
    return map(str.strip, split)


def parser(
    _: Item, extraction: object, objconf: FetchPageObjconf, **kwargs: object
) -> Iterator[str]:
    """
    Fetches the page and returns the requested slice.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `start`, `end`, `token` and
            `detag`.

    Returns:
        One string, or one per ``token`` separated piece. Each is stripped of
        surrounding whitespace.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from meza.fntools import Objectify
        >>> from riko import get_path
        >>>
        >>> url = get_path("cnn.html")
        >>> conf = {"url": url, "start": "<title>", "end": "</title>"}
        >>> objconf = Objectify(conf)
        >>> kwargs = {"stream": {}, "assign": "content"}
        >>> result = parser(None, None, objconf, **kwargs)
        >>> next(result)[:21]
        'CNN.com International'

    """
    url: str = require_conf(objconf, "url", "fetchpage")
    with Fetch(url, encoding=objconf.encoding) as f:
        sliced = betwix(f, objconf.start, objconf.end, True)
        content = "\n".join(sliced)

    parsed = get_string(content, objconf.start or "", objconf.end or "")
    detagged = get_text(parsed) if objconf.detag else parsed
    split = detagged.split(objconf.token) if objconf.token else [detagged]
    return map(str.strip, split)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[str]:
    """
    Asynchronously fetches the content of a web page as a string.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to fetch, local or remote. Required.

            start (str): Text marking where to begin, exclusive. The page is
                taken from the top when unset (default: None).

            end (str): Text marking where to stop, exclusive. The page is taken
                to the bottom when unset (default: None).

            token (str): Delimiter to split the result on, yielding one item per
                piece (default: None).

            detag (bool): Whether to strip html tags from the result
                (default: False).

            encoding (str): Page encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each string is assigned to. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each string directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<text>`` as a bare string when ``emit`` is True (default)
        - ``{<assign>: <text>}`` when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<text>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     url, path = get_path("bbc.html"), "value.items"
        ...     conf = {"url": url, "start": "DOCTYPE ", "end": "http"}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result))
        >>>
        >>> run(main)
        html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[str]:
    """
    Fetches the content of a web page as a string.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to fetch, local or remote. Required.

            start (str): Text marking where to begin, exclusive. The page is
                taken from the top when unset (default: None).

            end (str): Text marking where to stop, exclusive. The page is taken
                to the bottom when unset (default: None).

            token (str): Delimiter to split the result on, yielding one item per
                piece (default: None).

            detag (bool): Whether to strip html tags from the result
                (default: False).

            encoding (str): Page encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each string is assigned to. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each string directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<text>`` as a bare string when ``emit`` is True (default)
        - ``{<assign>: <text>}`` when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<text>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path("bbc.html")
        >>> conf = {"url": url, "start": "DOCTYPE ", "end": "http"}
        >>> next(pipe(conf=conf))
        'html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'

    """
    return parser(*args, **kwargs)
