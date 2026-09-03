# vim: sw=4:ts=4:expandtab
"""
Fetches the first RSS or Atom feed discovered on a page.

Uses the page's auto-discovery links to find a feed, then fetches and parses it.
Only the first feed found is used. Because the url is rediscovered on each run,
a site that later moves its feed keeps working, provided it updates its
auto-discovery links.

Not every site advertises auto-discovery links. Where one does and you want the
list of feeds rather than their contents, use the feedautodiscovery module,
which reports every feed found without fetching any of them.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchsitefeed import pipe
        >>>
        >>> next(pipe(conf={"url": get_path("bbc.html")}))["title"]
        "EU sets out 'phased' Brexit strategy"

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any

import pygogo as gogo

from riko import autorss
from riko._rssutils import augment_entries
from riko.bado.io import async_url_read
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.parsers import parse_rss
from riko.types._configs import FetchSiteFeedObjconf
from riko.types._options import Defaults, Opts
from riko.types._rss import RSSEntry
from riko.types._streams import Item

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: object, objconf: FetchSiteFeedObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Asynchronously discovers the first feed on a page and parses it.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and `user_agent`.

    Returns:
        Feed entries, or nothing when the page advertises no feed.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     objconf = Objectify({"url": get_path("bbc.html")})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        EU sets out 'phased' Brexit strategy

    """
    url: str = require_conf(objconf, "url", "fetchsitefeed")
    rss = await autorss.async_get_rss(url, user_agent=objconf.user_agent)

    if (first := next(rss, None)) is None:
        logger.warning(f"No feed found at {url}")
        entries = []
    else:
        content = await async_url_read(
            str(first["link"]), user_agent=objconf.user_agent
        )
        entries = parse_rss(content=content)

    return augment_entries(entries)


def parser(
    _: Item, extraction: object, objconf: FetchSiteFeedObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Discovers the first feed on a page and parses it.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and `user_agent`.

    Returns:
        Feed entries, or nothing when the page advertises no feed.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"url": get_path("bbc.html")})
        >>> result = parser(None, None, objconf)
        >>> next(result)["title"]
        "EU sets out 'phased' Brexit strategy"

    """
    url: str = require_conf(objconf, "url", "fetchsitefeed")
    rss = autorss.get_rss(url, user_agent=objconf.user_agent)

    if (first := next(rss, None)) is None:
        logger.warning(f"No feed found at {url}")
        entries = []
    else:
        entries = parse_rss(str(first["link"]), user_agent=objconf.user_agent)

    return augment_entries(entries)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[RSSEntry]:
    """
    Asynchronously fetches and parses the first feed found on a page.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to examine, local or remote. Required.
            user_agent (str): HTTP User-Agent override; unset uses riko's default.

        context (Context): the execution context

    Kwargs:
        assign (str): Field each entry is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each entry directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<entry>`` when ``emit`` is True (default)
        - ``{<assign>: <entry>}`` when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<entry>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Notes:
        A page advertising no feed yields nothing and logs a warning.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     result = await async_pipe(conf={"url": get_path("bbc.html")})
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        EU sets out 'phased' Brexit strategy

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[RSSEntry]:
    """
    Fetches and parses the first feed found on a page.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to examine, local or remote. Required.
            user_agent (str): HTTP User-Agent override; unset uses riko's default.

        context (Context): the execution context

    Kwargs:
        assign (str): Field each entry is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each entry directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<entry>`` when ``emit`` is True (default)
        - ``{<assign>: <entry>}`` when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<entry>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Notes:
        A page advertising no feed yields nothing and logs a warning.

    Examples:
        >>> from riko import get_path
        >>>
        >>> next(pipe(conf={"url": get_path("bbc.html")}))["title"]
        "EU sets out 'phased' Brexit strategy"

    """
    return parser(*args, **kwargs)
