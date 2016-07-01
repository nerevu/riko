# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.input
~~~~~~~~~~~~~~~~~~
Provides functions for obtaining and parsing user input.

Use this module any time you need to obtain and parse user input to wire into
another pipe. Supported parsers are 'text', 'int', 'float', 'bool', 'url', and
'date'.

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

        >>> from riko.modules.input import pipe
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> next(pipe(conf=conf, inputs={'content': '30'})) == {'content': 30}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import processor
from riko.lib import utils
import pygogo as gogo

OPTS = {'ftype': 'none'}
DEFAULTS = {'type': 'text', 'default': ''}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_, objconf, skip, **kwargs):
    """ Obtains the user input

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't prompt for input

    Returns:
        Tuple(dict, bool): Tuple of (the casted user input, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> inputs = {'age': '30'}
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'inputs': inputs, 'assign': 'age'}
        >>> parser(None, objconf, False, **kwargs)[0] == {'age': 30}
        True
    """
    if kwargs.get('inputs'):
        value = kwargs['inputs'].get(kwargs['assign'], objconf.default)
    elif kwargs.get('test') or skip:
        value = objconf.default
    else:
        raw = input("%s (default=%s) " % (objconf.prompt, objconf.default))
        value = raw or objconf.default

    casted = utils.cast(value, objconf.type)
    result = casted if hasattr(casted, 'keys') else {kwargs['assign']: casted}
    return result, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
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
            type (str): Expected value type. Must be one of 'text', 'int',
                'float', 'bool', 'url', 'location', or 'date'. Default: 'text'.
            assign (str): Attribute to assign parsed content (default: content)

        inputs (dict): values to be used in place of prompting the user e.g.
            {'name': 'value1'}

        test (bool): Take input values from default (skip the console prompt)
        verbose (bool): Show debug messages when running pipe

    Returns:
       Deferred: twisted.internet.defer.Deferred iterator of items of user input

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'content': 30})
        ...     conf = {'prompt': 'How old are you?', 'type': 'int'}
        ...     d = async_pipe(conf=conf, inputs={'content': '30'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
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
            'default', 'type'.

            prompt (str): User command line prompt
            default (scalar): Default value
            type (str): Expected value type. Must be one of 'text', 'int',
                'float', 'bool', 'url', 'location', or 'date'. Default: 'text'.

        assign (str): Attribute to assign parsed content (default: content)

        inputs (dict): values to be used in place of prompting the user e.g.
            {'name': 'value1'}

        test (bool): Take input values from default (skip the console prompt)
        verbose (bool): Show debug messages when running pipe

    Yields:
       dict: item of user input

    Examples:
        >>> # int
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> next(pipe(conf=conf, inputs={'content': '30'})) == {'content': 30}
        True
        >>>
        >>> # date
        >>> import datetime
        >>>
        >>> conf = {'prompt': 'When were you born?', 'type': 'date'}
        >>> result = next(pipe(conf=conf, inputs={'content': '5/4/82'}))
        >>> sorted(result.keys()) == [
        ...     'date', 'day', 'day_of_week', 'day_of_year',
        ...     'daylight_savings', 'hour', 'minute', 'month',
        ...     'second', 'timezone', 'utime', 'year']
        True
        >>> result['date']
        datetime.datetime(1982, 5, 4, 0, 0)
        >>>
        >>> stream = pipe(conf={'type': 'date'}, inputs={'content': 'tomorrow'})
        >>> d = next(stream)
        >>> sorted(d.keys()) == [
        ...     'date', 'day', 'day_of_week', 'day_of_year',
        ...     'daylight_savings', 'hour', 'minute', 'month', 'second',
        ...     'timezone', 'utime', 'year']
        True
        >>> td = d['date'] - datetime.datetime.utcnow()
        >>> hours = td.total_seconds() / 3600
        >>> 24 > hours > 23
        True
        >>> # float, bool, text
        >>> matrix = [
        ...     ('float', '1', 1.0),
        ...     ('bool', 'true', True),
        ...     ('text', 'hello', 'hello')]
        >>>
        >>> for t, c, r in matrix:
        ...     kwargs = {'conf': {'type': t}, 'inputs': {'content': c}}
        ...     next(pipe(**kwargs)) == {'content': r}
        True
        True
        True
        >>> # url
        >>> inputs = {'content': 'google.com'}
        >>> result = next(pipe(conf={'type': 'url'}, inputs=inputs))
        >>> sorted(result.keys())== [
        ...     'fragment', 'netloc', 'params', 'path', 'query', 'scheme',
        ...     'url']
        True
        >>> result['url'] == 'http://google.com'
        True
        >>> # location
        >>> inputs = {'content': 'palo alto, ca'}
        >>> result = next(pipe(conf={'type': 'location'}, inputs=inputs))
        >>> sorted(result.keys()) == [
        ...     'admin1', 'admin2', 'admin3', 'city', 'country', 'lat',
        ...     'lon', 'postal', 'quality', 'street']
        True
        >>> result['city'] == 'city'
        True
    """
    return parser(*args, **kwargs)
