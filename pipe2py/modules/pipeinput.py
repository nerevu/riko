# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipeinput
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for obtaining and parsing user input.

Use this module any time you need to obtain and parse user input to wire into
another pipe. Supported parsers are 'text', 'int', 'float', 'bool', 'unicode',
'url', and 'date'.

Valid Date Values

Obvious date formats:

    Jan. 12, 2001
    10/21/1958
    15 JUN 06

Plus some unusual formats as well:

    now
    today
    yesterday
    tomorrow
    +3 days
    -10 weeks
    last year
    next month
    1181230100

Note: Relative date/time calculations reference the current UTC time. Timezones
are not currently supported.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipeinput import pipe
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> pipe(conf=conf, inputs={'content': '30'}).next()
        {u'content': 30}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from . import processor
from pipe2py.lib import utils
from pipe2py.lib.log import Logger

OPTS = {'ftype': 'none'}
DEFAULTS = {'type': 'text'}
logger = Logger(__name__).logger


def parser(_, objconf, skip, **kwargs):
    """ Obtains the user input

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't prompt for input

    Returns:
        Tuple(dict, bool): Tuple of (the casted user input, skip)

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> inputs = {'age': '30'}
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> objconf = Objectify(conf)
        >>> parser(None, objconf, False, inputs=inputs, assign='age')[0]
        {u'age': 30}
    """
    if kwargs['inputs']:
        value = kwargs['inputs'].get(kwargs['assign'], objconf.default)
    elif objconf.test or skip:
        value = objconf.default
    else:
        raw = raw_input("%s (default=%s) " % (objconf.prompt, objconf.default))
        value = raw or objconf.default

    casted = utils.cast(value, objconf.type)
    result = casted if hasattr(casted, 'keys') else {kwargs['assign']: casted}
    return result, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously prompts for text and parses it
    into a variety of different types, e.g., int, bool, date, etc.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'prompt',
            'default', 'type', 'assign'.

            prompt (str): User command line prompt
            default (scalar): Default value
            type (str): Expectd value type. Must be one of 'text', 'int',
                'float', 'bool', 'unicode', 'url', or 'date'. Default: 'text'.
            assign (str): Attribute to assign parsed content (default: content)

        inputs (dict): values that overrides the defaults e.g.
            {'name': 'value1'}

        test (bool): Take input values from default (skip the console prompt)
        verbose (bool): Show debug messages when running pipe

    Returns:
       Deferred: twisted.internet.defer.Deferred iterator of items of user input

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next())
        ...     conf = {'prompt': 'How old are you?', 'type': 'int'}
        ...     d = asyncPipe(conf=conf, inputs={'content': '30'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': 30}
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor module that prompts for text and parses it into a variety of
    different types, e.g., int, bool, date, etc.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'prompt',
            'default', 'type', 'assign'.

            prompt (str): User command line prompt
            default (scalar): Default value
            type (str): Expectd value type. Must be one of 'text', 'int',
                'float', 'bool', 'unicode', 'url', or 'date'. Default: 'text'.
            assign (str): Attribute to assign parsed content (default: content)

        inputs (dict): values that overrides the defaults e.g.
            {'name': 'value1'}

        test (bool): Take input values from default (skip the console prompt)
        verbose (bool): Show debug messages when running pipe

    Yields:
       dict: item of user input

    Examples:
        >>> # int
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> pipe(conf=conf, inputs={'content': '30'}).next()
        {u'content': 30}
        >>>
        >>> # date
        >>> import datetime
        >>>
        >>> conf = {'prompt': 'When were you born?', 'type': 'date'}
        >>> result = pipe(conf=conf, inputs={'content': '5/4/82'}).next()
        >>> sorted(result.keys()) == [
        ...     u'date', u'day', u'day_of_week', u'day_of_year',
        ...     u'daylight_savings', u'hour', u'minute', u'month',
        ...     u'second', u'timezone', u'utime', u'year']
        True
        >>> result['date']
        datetime.datetime(1982, 5, 4, 0, 0)
        >>> d = pipe(conf=conf, inputs={'content': 'tomorrow'}).next()['date']
        >>> td = d - datetime.datetime.utcnow()
        >>> 24 > td.total_seconds() / 3600 > 23
        True
        >>>
        >>> # url
        >>> inputs = {'content': 'google.com'}
        >>> result = pipe(conf={'type': 'url'}, inputs=inputs).next()
        >>> sorted(result.keys())
        ['fragment', 'netloc', 'params', 'path', 'query', 'scheme', u'url']
        >>> result['url']
        u'http://google.com'
        >>>
        >>> # location
        >>> inputs = {'content': 'palo alto, ca'}
        >>> result = pipe(conf={'type': 'location'}, inputs=inputs).next()
        >>> sorted(result.keys()) == [
        ...     u'admin1', u'admin2', u'admin3', u'city', u'country', u'lat',
        ...     u'lon', u'postal', u'quality', u'street']
        True
        >>> result['city']
        u'city'
    """
    return parser(*args, **kwargs)
