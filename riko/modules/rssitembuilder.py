# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating a single-item RSS data source

Can be used to create a single new RSS item from scratch, or reformat and
restructure an existing item into an RSS structure.

Examples:
    basic usage::

        >>> from riko.modules.rssitembuilder import pipe
        >>>
        >>> conf = {'title': 'the title', 'description': 'description'}
        >>> next(pipe(conf=conf))['y:title']
        'the title'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from typing import cast

import pygogo as gogo

from riko.dates import NOW
from riko.dotdict import DotDict
from riko.types.configs import RssItemBuilderObjconf
from riko.types.general import Defaults, Extraction, Item, Opts

from . import processor

OPTS: Opts = {"emit": True}
DEFAULTS: Defaults = {"pubDate": NOW.isoformat()}
logger = gogo.Gogo(__name__, monolog=True).logger


# yahoo style rss items (dots are for sub-levels)
rss = {
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

RSS = cast(dict[str, str], DotDict(rss))


def parser(
    item: Item, extraction: Extraction, objconf: RssItemBuilderObjconf, **kwargs
) -> DotDict:
    """
    Parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict()
        >>> conf = {'guid': 'a1', 'mediaThumbURL': 'image.png'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'stream': item}
        >>> parser(item, None, objconf, **kwargs)
        {'y:id': 'a1', 'media:thumbnail': {'url': 'image.png'}}

    """
    rdict = {RSS[k]: v for k, v in objconf.iteritems() if k in RSS}
    stream = DotDict(rdict)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> DotDict:
    """
    A source that asynchronously builds an rss item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. All keys are optional.

            title (str): The item title
            description (str): The item description
            author (str): The item author
            guid (str): The item guid
            pubdate (str): The item publication date
            link (str): The item url
            mediaContentType (str): The item media content type
            mediaContentURL (str): The item media content url
            mediaContentHeight (str): The item media content height
            mediaContentWidth (str): The item media content width
            mediaThumbURL (str): The item media thumbnail url
            mediaThumbHeight (str): The item media thumbnail height
            mediaThumbWidth (str): The item media thumbnail width

    Returns:
        Awaitable: an iterator of items

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     conf = {'title': 'Hi', 'guid': 'a1', 'mediaThumbURL': 'image.png'}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result)['media:thumbnail'])
        >>>
        >>> run(main)
        {'url': 'image.png'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> DotDict:
    """
    A source that builds an rss item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. All keys are optional.

            title (str): The item title
            description (str): The item description
            author (str): The item author
            guid (str): The item guid
            pubdate (str): The item publication date
            link (str): The item url
            mediaContentType (str): The item media content type
            mediaContentURL (str): The item media content url
            mediaContentHeight (str): The item media content height
            mediaContentWidth (str): The item media content width
            mediaThumbURL (str): The item media thumbnail url
            mediaThumbHeight (str): The item media thumbnail height
            mediaThumbWidth (str): The item media thumbnail width

    Yields:
        dict: an rss item

    Examples:
        >>> # conf based
        >>> conf = {'title': 'Hi', 'guid': 'a1', 'mediaThumbURL': 'image.png'}
        >>> rss = next(pipe(conf=conf))
        >>> sorted(rss)
        ['media:thumbnail', 'pubDate', 'y:id', 'y:title']
        >>> rss['media:thumbnail']
        {'url': 'image.png'}
        >>>
        >>> # source based
        >>> item = {'thumbnail': 'image.png'}
        >>> conf = {'mediaThumbURL': {'subkey': 'thumbnail'}}
        >>> next(pipe(item, conf=conf))['media:thumbnail']
        {'url': 'image.png'}

    """
    return parser(*args, **kwargs)
