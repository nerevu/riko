# vim: sw=4:ts=4:expandtab
"""
Builds a single RSS item from configured attributes.

Maps friendly conf names such as ``title`` and ``mediaThumbURL`` onto their
Yahoo style RSS equivalents, nesting the dotted targets. Use it to create an
RSS item from scratch, or to restructure an existing item into RSS form by
reading its values with ``subkey``.

Examples:
    Basic usage::

        >>> from riko.modules.rssitembuilder import pipe
        >>>
        >>> conf = {"title": "the title", "description": "description"}
        >>> next(pipe(conf=conf))["y:title"]
        'the title'

Attributes:
    RSS: Maps each conf key onto its RSS field, dots marking sub-levels.
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from datetime import UTC
from datetime import datetime as dt
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko.cast import BasicCastType
from riko.dotdict import DotDict
from riko.types.configs import RssItemBuilderObjconf
from riko.types.general import Defaults, Extraction, Item, Opts
from riko.types.values import RikoValue

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger

RSS = cast(
    dict[str, str],
    DotDict(
        {
            "author": "author",
            "description": "description",
            "guid": "y:id",
            "link": "link",
            "mediaContentHeight": "media:content.height",
            "mediaContentType": "media:content.type",
            "mediaContentURL": "media:content.url",
            "mediaContentWidth": "media:content.width",
            "mediaThumbHeight": "media:thumbnail.height",
            "mediaThumbURL": "media:thumbnail.url",
            "mediaThumbWidth": "media:thumbnail.width",
            "pubDate": "pubDate",
            "title": "y:title",
        }
    ),
)


def parser(
    _: Item, extraction: Extraction, objconf: RssItemBuilderObjconf, **kwargs: object
) -> DotDict[RikoValue]:
    """
    Builds an RSS item from the configured attributes.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, supplying the RSS attributes.

    Returns:
        The RSS item, dated now unless ``pubDate`` says otherwise.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {"guid": "a1", "mediaThumbURL": "img.png", "pubDate": "today"}
        >>> parser({}, None, Objectify(conf), stream={})
        {'y:id': 'a1', 'media:thumbnail': {'url': 'img.png'}, 'pubDate': 'today'}

    """
    rdict = {RSS[k]: v for k, v in objconf.iteritems() if k in RSS}
    rdict.setdefault("pubDate", dt.now(UTC).isoformat())
    return DotDict(rdict)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> DotDict[RikoValue]:
    """
    Asynchronously builds a single RSS item.

    Args:
        item (Item | Items): The entry, or stream of entries, supplying values.
        conf (dict): The pipe configuration. Every key is optional, and each
            value is either a literal or a ``{"subkey": ...}`` reference
            reading it from ``item``.

            author (str): Maps to ``author``.
            description (str): Maps to ``description``.
            guid (str): Maps to ``y:id``.
            link (str): Maps to ``link``.
            mediaContentHeight (str): Maps to ``media:content.height``.
            mediaContentType (str): Maps to ``media:content.type``.
            mediaContentURL (str): Maps to ``media:content.url``.
            mediaContentWidth (str): Maps to ``media:content.width``.
            mediaThumbHeight (str): Maps to ``media:thumbnail.height``.
            mediaThumbURL (str): Maps to ``media:thumbnail.url``.
            mediaThumbWidth (str): Maps to ``media:thumbnail.width``.
            pubDate (str): Maps to ``pubDate`` (default: the current time).
            title (str): Maps to ``y:title``.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the RSS item is nested under. Ignored when ``emit``
            is True (default: "content").

        emit (bool): Whether to emit the RSS item directly rather than assign
            it. Overrides ``assign`` (default: True).

    Yields:
        - the RSS item when ``emit`` is True (default)
        - ``{<assign>: <rss item>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <rss item>}`` when ``emit`` is False and item
          is given

    Notes:
        A conf key with no RSS equivalent is dropped.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"title": "Hi", "guid": "a1", "mediaThumbURL": "img.png"}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result)["media:thumbnail"])
        >>>
        >>> run(main)
        {'url': 'img.png'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> DotDict[RikoValue]:
    """
    Builds a single RSS item.

    Args:
        item (Item | Items): The entry, or stream of entries, supplying values.
        conf (dict): The pipe configuration. Every key is optional, and each
            value is either a literal or a ``{"subkey": ...}`` reference
            reading it from ``item``.

            author (str): Maps to ``author``.
            description (str): Maps to ``description``.
            guid (str): Maps to ``y:id``.
            link (str): Maps to ``link``.
            mediaContentHeight (str): Maps to ``media:content.height``.
            mediaContentType (str): Maps to ``media:content.type``.
            mediaContentURL (str): Maps to ``media:content.url``.
            mediaContentWidth (str): Maps to ``media:content.width``.
            mediaThumbHeight (str): Maps to ``media:thumbnail.height``.
            mediaThumbURL (str): Maps to ``media:thumbnail.url``.
            mediaThumbWidth (str): Maps to ``media:thumbnail.width``.
            pubDate (str): Maps to ``pubDate`` (default: the current time).
            title (str): Maps to ``y:title``.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the RSS item is nested under. Ignored when ``emit``
            is True (default: "content").

        emit (bool): Whether to emit the RSS item directly rather than assign
            it. Overrides ``assign`` (default: True).

    Yields:
        - the RSS item when ``emit`` is True (default)
        - ``{<assign>: <rss item>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <rss item>}`` when ``emit`` is False and item
          is given

    Notes:
        A conf key with no RSS equivalent is dropped.

    Examples:
        >>> conf = {"title": "Hi", "guid": "a1", "mediaThumbURL": "img.png"}
        >>> rss = next(pipe(conf=conf))
        >>> sorted(rss)
        ['media:thumbnail', 'pubDate', 'y:id', 'y:title']
        >>> rss["media:thumbnail"]
        {'url': 'img.png'}
        >>> item = {"thumbnail": "img.png"}
        >>> conf = {"mediaThumbURL": {"subkey": "thumbnail"}}
        >>> next(pipe(item, conf=conf))["media:thumbnail"]
        {'url': 'img.png'}

    """
    return parser(*args, **kwargs)
