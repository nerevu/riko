# vim: sw=4:ts=4:expandtab
"""
Discovers RSS/Atom feed links on a page.

Examines a page for information about the feeds it advertises, e.g., ``link rel`` tags.
It yields found feeds. The output is typically piped into ``fetch`` to retrieve and
parse the feeds.

Since not every site advertises auto-discovery links, the fetchsitefeed module can be
used instead to return the content of the first discovered feed.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.feedautodiscovery import pipe
        >>>
        >>> url = get_path("bbc.html")
        >>> entry = next(pipe(conf={"url": url}))
        >>> entry["link"]
        'file://riko/data/bbci.co.uk.xml'
        >>> sorted(entry)
        ['href', 'link', 'rel', 'tag', 'title', 'type']
        >>> entry["type"]
        'application/rss+xml'
        >>> entry = next(pipe(conf={"url": url, "strict": False}))
        >>> entry["link"]
        'greenhughes.xml'
        >>> sorted(entry)
        ['href', 'hreflang', 'link', 'rel', 'tag']
        >>> next(pipe(conf={"url": url, "strict": False, "sort": True}))["link"]
        'file://riko/data/bbci.co.uk.xml'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko import autorss
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.types.configs import FeedAutoDiscoveryObjconf
from riko.types.general import Defaults, Extraction, Item, Opts, Stream

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {"strict": True, "sort": False}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: FeedAutoDiscoveryObjconf, **kwargs: object
) -> Stream:
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
    stream = await autorss.async_get_rss(url, link_type=None, **rkwargs)
    return stream


def parser(
    _: Item, extraction: Extraction, objconf: FeedAutoDiscoveryObjconf, **kwargs: object
) -> Stream:
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
    stream = autorss.get_rss(url, link_type=None, **rkwargs)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
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
        ...     result = await async_pipe(conf={"url": get_path("bbc.html")})
        ...     print(next(result)["link"])
        >>>
        >>> run(main)
        file://riko/data/bbci.co.uk.xml

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
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
