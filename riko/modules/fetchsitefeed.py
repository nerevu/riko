# vim: sw=4:ts=4:expandtab
"""
Fetches and parses the first RSS or Atom feed advertised by a page.

Examples:

    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchsitefeed import pipe
        >>>
        >>> next(pipe(conf={"url": get_path("bbc.html")}))["title"]
        "EU sets out 'phased' Brexit strategy"

Attributes:

    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from riko.base._logging import get_logger
from riko.base._require_guards import require_conf_key
from riko.coercion.cast import SourceOpts
from riko.io._async import async_url_read
from riko.rss.discovery import aload_rss_links, load_rss_links
from riko.rss.feeds import augment_entries, parse_rss

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Iterator
    from logging import Logger

    from riko.coercion._configs import FetchSiteFeedObjconf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._rss import RSSEntry
    from riko.types._streams import Item

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = SourceOpts
DEFAULTS: Defaults = {}


async def async_parser(
    _: Item, extraction: object, objconf: FetchSiteFeedObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Asynchronously discovers the first feed on a page and parses it.

    Args:

        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The module configuration, containing `url`.

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
    url: str = require_conf_key(objconf, "url", "fetchsitefeed")
    rss = await aload_rss_links(url)

    if (first := next(rss, None)) is None:
        logger.warning(f"No feed found at {url}")
        entries = []
    else:
        content = await async_url_read(str(first.get("link")))
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
        objconf: The module configuration, containing `url`.

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
    url: str = require_conf_key(objconf, "url", "fetchsitefeed")
    rss = load_rss_links(url)

    if (first := next(rss, None)) is None:
        logger.warning(f"No feed found at {url}")
        entries = []
    else:
        entries = parse_rss(str(first.get("link")))

    return augment_entries(entries)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[RSSEntry]:
    """
    Asynchronously fetches and parses the first feed found on a page.

    Args:

        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The module configuration.

            url (str): The page to examine, local or remote. Required.

        context (Context): the run environment

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
        ...     result = async_pipe(conf={"url": get_path("bbc.html")})
        ...     print((await anext(result))["title"])
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

        conf (dict): The module configuration.

            url (str): The page to examine, local or remote. Required.

        context (Context): the run environment

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
