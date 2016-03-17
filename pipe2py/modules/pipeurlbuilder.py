# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipeurlbuilder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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

If we want to use this feed service in our Pipe, we can just drop a Fetch Feed
module into the Editor and type the URL in. But then our Pipe is stuck reading
data for just one ticker symbol. We could wire in a URL Input module, but then
the user has to enter the whole URL.

The better way is to use URL Builder. This module constructs a URL for you from
parts. Some parts you may type in, others you may wire in using Text User Input
modules.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipeurlbuilder import pipe
        >>>
        >>> params = {'key': 's', 'value': 'gm'}
        >>> path = [{'value': 'rss'}, {'value': 'headline'}]
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'params': params}
        >>> pipe(conf=conf).next()['urlbuilder']
        u'http://finance.yahoo.com/rss/headline?s=gm'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from . import processor
from pipe2py.lib.log import Logger
from pipe2py.lib.dotdict import DotDict
from pipe2py.lib.utils import url_quote, get_value

OPTS = {'extract': 'params', 'listize': True}
DEFAULTS = {}
logger = Logger(__name__).logger


def parser(item, params, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        params (List[dict]): Query parameters
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple (dict, bool): Tuple of (item, skip)

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> item = DotDict()
        >>> params = {'key': 's', 'value': 'gm'}
        >>> path = [{'value': 'rss'}, {'value': 'headline'}]
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'params': params}
        >>> kwargs = {'feed': item, 'conf': conf}
        >>> parser(item, [Objectify(params)], False, **kwargs)[0]
        u'http://finance.yahoo.com/rss/headline?s=gm'
    """
    if skip:
        feed = kwargs['feed']
    else:
        conf = kwargs.pop('conf')
        paths = (get_value(item, DotDict(p), **kwargs) for p in conf.get('path'))
        url = '%s/%s' % (conf.get('base', '').rstrip('/'),  '/'.join(paths))
        params = [(p.key, p.value) for p in params]
        feed = url_quote(url, params=params)

    return feed, skip


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

        assign (str): Attribute to assign parsed content (default: urlbuilder)

    Yields:
        dict: a url

    Examples:
        >>> params = {'key': 's', 'value': 'gm'}
        >>> path = [{'value': 'rss'}, {'value': 'headline'}]
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'params': params}
        >>> pipe(conf=conf).next()['urlbuilder']
        u'http://finance.yahoo.com/rss/headline?s=gm'
    """
    return parser(*args, **kwargs)

