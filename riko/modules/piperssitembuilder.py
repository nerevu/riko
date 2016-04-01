# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.piperssitembuilder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for creating a single-item RSS data source

Can be used to create a single new RSS item from scratch, or reformat and
restructure an existing item into an RSS structure.

Examples:
    basic usage::

        >>> from riko.modules.piperssitembuilder import pipe
        >>> conf = {'title': 'the title', 'description': 'description'}
        >>> next(pipe(conf=conf))['y:title']
        u'the title'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from datetime import datetime as dt

from builtins import *

from . import processor
from riko.lib.log import Logger
from riko.lib.dotdict import DotDict

OPTS = {'emit': True}
DEFAULTS = {'pubDate': dt.now().isoformat()}
logger = Logger(__name__).logger


# yahoo style rss items (dots are for sub-levels)
RSS = {
    'title': 'y:title',
    'guid': 'y:id',
    'mediaThumbURL': 'media:thumbnail.url',
    'mediaThumbHeight': 'media:thumbnail.height',
    'mediaThumbWidth': 'media:thumbnail.width',
    'mediaContentType': 'media:content.type',
    'mediaContentURL': 'media:content.url',
    'mediaContentHeight': 'media:content.height',
    'mediaContentWidth': 'media:content.width'}


def parser(item, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from riko.lib.dotdict import DotDict
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = DotDict()
        >>> conf = {'guid': 'a1', 'mediaThumbURL': 'image.png'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'feed': item}
        >>> result, skip = parser(item, objconf, False, **kwargs)
        >>> result == {'media:thumbnail': {'url': 'image.png'}, 'y:id': 'a1'}
        True
    """
    if skip:
        feed = kwargs['feed']
    else:
        items = objconf.items()
        rdict = ((RSS.get(k, k), item.get(v, v, **kwargs)) for k, v in items)
        feed = DotDict(rdict)

    return feed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously builds an rss item.

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
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['media:thumbnail'])
        ...     conf = {
        ...         'title': 'Hi', 'guid': 'a1', 'mediaThumbURL': 'image.png'}
        ...     d = asyncPipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        {u'url': u'image.png'}
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that builds an rss item.

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
        >>> rss['media:thumbnail']
        {u'url': u'image.png'}
        >>> sorted(rss.keys())
        [u'media:thumbnail', u'pubDate', u'y:id', u'y:title']
        >>>
        >>> # source based
        >>> # TODO: look into subkey
        >>> item = {'heading': 'Hi', 'id': 'a1', 'thumbnail': 'image.png'}
        >>> conf = {
        ...     'title': 'heading', 'guid': 'id', 'mediaThumbURL': 'thumbnail'}
        >>> next(pipe(item, conf=conf)) == rss
        True
    """
    return parser(*args, **kwargs)
