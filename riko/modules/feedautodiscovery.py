# vim: sw=4:ts=4:expandtab
"""
Discovers RSS/Atom feed links advertised by a page.

Examples:

    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.feedautodiscovery import pipe
        >>>
        >>> url = get_path("bbc.html")
        >>> next(pipe(conf={"url": url}))["link"]
        'file://riko/data/bbci.co.uk.xml'

Attributes:

    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pygogo as gogo

from riko.coercion.cast import SourceOpts
from riko.rss.discovery import async_get_rss, get_rss

from ._decorators import processor
from ._prepare import require_conf

if TYPE_CHECKING:
    from logging import Logger

    from riko.coercion._configs import FeedAutoDiscoveryObjconf
    from riko.types._options import Defaults, Opts
    from riko.types._streams import Record, RecordStream

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {"strict": True, "sort": False}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Record, extraction: object, objconf: FeedAutoDiscoveryObjconf, **kwargs: object
) -> RecordStream:
    """
    Asynchronously discovers the feed links advertised by a page.

    Args:

        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `strict` and `sort`.

    Returns:

        One item per discovered feed link.

    Raises:

        TypeError: If ``conf`` has no ``url`` key.

    Examples:

        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     objconf = Objectify({"url": get_path("bbc.html"), "strict": True})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)["link"])
        >>>
        >>> run(main)
        file://riko/data/bbci.co.uk.xml

    """
    url: str = require_conf(objconf, "url", "feedautodiscovery")
    rkwargs = {"auto_sort": objconf.sort, "strict": objconf.strict}
    stream = await async_get_rss(url, link_type=None, **rkwargs)
    return stream


def parser(
    _: Record, extraction: object, objconf: FeedAutoDiscoveryObjconf, **kwargs: object
) -> RecordStream:
    """
    Discovers the feed links advertised by a page.

    Args:

        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `strict` and `sort`.

    Returns:

        One item per discovered feed link.

    Raises:

        TypeError: If ``conf`` has no ``url`` key.

    Examples:

        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path("bbc.html")
        >>> objconf = Objectify({"url": url, "strict": True})
        >>> next(parser(None, None, objconf))["link"]
        'file://riko/data/bbci.co.uk.xml'
        >>> objconf = Objectify({"url": url, "strict": False})
        >>> next(parser(None, None, objconf))["link"]
        'greenhughes.xml'
        >>> objconf = Objectify({"url": url, "strict": False, "sort": True})
        >>> next(parser(None, None, objconf))["link"]
        'file://riko/data/bbci.co.uk.xml'

    """
    url: str = require_conf(objconf, "url", "feedautodiscovery")
    rkwargs = {"auto_sort": objconf.sort, "strict": objconf.strict}
    stream = get_rss(url, link_type=None, **rkwargs)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> RecordStream:
    """
    Asynchronously discovers RSS/Atom feed links on a page.

    Args:

        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to examine, local or remote. Required.

            strict (bool): Whether to return only links that declare a feed
                type. Loosening this finds more links but they carry fewer
                fields (default: True).

            sort (bool): Whether to order links by how likely each is to be a
                feed, rather than document order (default: False).

        context (Context): the execution context

    Kwargs:

        assign (str): Field each link is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each link directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:

        - ``<link>`` per discovered feed when ``emit`` is True (default)
        - ``{<assign>: <link>}`` per feed when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<link>, ...]}`` when ``emit`` is False and
          item is given

    Raises:

        TypeError: If ``conf`` has no ``url`` key.

    Examples:

        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     result = async_pipe(conf={"url": get_path("bbc.html")})
        ...     print((await anext(result))["link"])
        >>>
        >>> run(main)
        file://riko/data/bbci.co.uk.xml

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> RecordStream:
    """
    Discovers RSS/Atom feed links on a page.

    Args:

        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to examine, local or remote. Required.

            strict (bool): Whether to return only links that declare a feed
                type. Loosening this finds more links but they carry fewer
                fields (default: True).

            sort (bool): Whether to order links by how likely each is to be a
                feed, rather than document order (default: False).

        context (Context): the execution context

    Kwargs:

        assign (str): Field each link is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each link directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:

        - ``<link>`` per discovered feed when ``emit`` is True (default)
        - ``{<assign>: <link>}`` per feed when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<link>, ...]}`` when ``emit`` is False and
          item is given

    Raises:

        TypeError: If ``conf`` has no ``url`` key.

    Examples:

        >>> from riko import get_path
        >>>
        >>> conf = {"url": get_path("bbc.html")}
        >>> next(pipe(conf=conf))["link"]
        'file://riko/data/bbci.co.uk.xml'

    """
    return parser(*args, **kwargs)
