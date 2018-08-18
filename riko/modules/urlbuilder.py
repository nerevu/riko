# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.urlbuilder
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for building a url from parts

Many URLs are long and complex. Modules like Fetch Feed let you provide a URL
as a starting point for a Pipe, but sometimes you'd like to control how that
URL is constructed. That's what the URL Builder module does.

To see how this works, and why it can be useful, lets look at an example URL:

    http://finance.yahoo.com/rss/headline?s=yhoo

One of Yahoo! Finance's RSS services lets you get news feeds for companies
based on their stock market ticker. The URL above returns news stories related
to Yahoo! (stock ticker YHOO). To get news on another company, for example
General Motors (stock ticker GM), you'd simply change the URL to:

    http://finance.yahoo.com/rss/headline?s=gm

URLs are built from three main parts. The first is a server name, in our
example that's "finance.yahoo.com". The second part is a resource path. That's
everything after the server name, up to (but not including) the question mark
("/rss/headline"). Finally, after the question mark are a series of parameters.

In our example, there's only one parameter, named s. The parameter name and its
value are separated by an equal sign, giving us "s=gm" or "s=yhoo".

If we want to use this service in our Pipe, we can just use a Fetch Feed
module and enter the URL. But then our Pipe is stuck reading data for just one
ticker symbol. We could wire in a URL Input module, but then the user has to
enter the whole URL.

The better way is to use URL Builder. This module constructs a URL for you from
parts. Some parts you may type in, others you may wire in using Text User Input
modules.

Examples:
    basic usage::

        >>> from riko.modules.urlbuilder import pipe
        >>>
        >>> params = {'key': 's', 'value': 'gm'}
        >>> path = [{'value': 'rss'}, {'value': 'headline'}]
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'params': params}
        >>> url = 'http://finance.yahoo.com/rss/headline?s=gm'
        >>> next(pipe(conf=conf))['url'] == url
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *  # noqa pylint: disable=unused-import
from six.moves.urllib.parse import urljoin, urlencode

from . import processor
import pygogo as gogo
from riko.dotdict import DotDict
from riko.parsers import get_value
from riko.cast import cast_url

OPTS = {'extract': 'params', 'listize': True, 'emit': True}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(item, params, skip=False, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        params (List[dict]): Query parameters
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict()
        >>> params = {'key': 's', 'value': 'gm'}
        >>> path = [{'value': 'rss'}, {'value': 'headline'}]
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'params': params}
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> result = parser(item, [Objectify(params)], **kwargs)
        >>> sorted(result.keys()) == [
        ...     'fragment', 'netloc', 'params', 'path', 'query', 'scheme',
        ...     'url']
        True
        >>> result['url'] == 'http://finance.yahoo.com/rss/headline?s=gm'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        conf = kwargs.pop('conf')
        path = conf.get('path')
        paths = (get_value(item, DotDict(p), **kwargs) for p in path)
        params = urlencode([(p.key, p.value) for p in params])
        url = '%s?%s' % (urljoin(conf['base'], '/'.join(paths)), params)
        stream = cast_url(url)

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously builds a url.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'base'. May
            contain the keys 'params' or 'path'.

            base (str): the sever name
            path (str): the resource path
            params (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the parameter name
                value (str): the parameter value

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['url'])
        ...     params = {'key': 's', 'value': 'gm'}
        ...     path = [{'value': 'rss'}, {'value': 'headline'}]
        ...     base = 'http://finance.yahoo.com'
        ...     conf = {'base': base, 'path': path, 'params': params}
        ...     d = async_pipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        http://finance.yahoo.com/rss/headline?s=gm
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that builds a url.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'base'. May
            contain the keys 'params' or 'path'.

            base (str): the sever name
            path (str): the resource path
            params (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the parameter name
                value (str): the parameter value

    Yields:
        dict: a url item

    Examples:
        >>> params = {'key': 's', 'value': 'gm'}
        >>> path = [{'value': 'rss'}, {'value': 'headline'}]
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'params': params}
        >>> result = next(pipe(conf=conf))
        >>> sorted(result.keys()) == [
        ...     'fragment', 'netloc', 'params', 'path', 'query', 'scheme',
        ...     'url']
        True
        >>> result['url'] == 'http://finance.yahoo.com/rss/headline?s=gm'
        True
    """
    return parser(*args, **kwargs)
