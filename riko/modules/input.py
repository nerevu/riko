# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.input
~~~~~~~~~~~~~~~~~~
Provides functions for obtaining and parsing user input.

Use this module any time you need to obtain and parse user input to wire into
another pipe. Supported parsers are 'text', 'int', 'float', 'bool', 'url', and
'date'. Not loopable.

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
        >>>
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> next(pipe(conf=conf, inputs={'content': '30'}))
        30
        >>> conf['test'] = True
        >>> next(pipe(conf=conf))
        0

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
import pygogo as gogo

from riko.cast import CastType, cast
from riko.types.general import ComplexArg, BasicArg, Defaults, Extraction

from . import processor
from riko import Objconf

OPTS = {"ftype": "none"}
DEFAULTS: Defaults = {"type": "text", "field": "content", "default": "", "test": False}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs) -> ComplexArg:
    """Obtains the user input

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't prompt for input

    Returns:
        dict: The casted user input

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> inputs = {'age': '30'}
        >>> conf = {'prompt': 'How old are you?', 'type': 'int', 'field': 'age'}
        >>> objconf = Objectify(conf)
        >>> parser(None, None, objconf, inputs=inputs)
        30
    """
    if kwargs.get("inputs"):
        value = kwargs["inputs"].get(objconf.field, objconf.default)
    elif objconf.test or skip:
        value = objconf.default
    else:
        raw = input(f"{objconf.prompt} (default={objconf.default}) ")
        value = raw or objconf.default

    return cast(value, CastType(objconf.type)) if objconf.type else value


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously prompts for text and parses it
    into a variety of different types, e.g., int, bool, date, etc.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'prompt',
            'default', or 'type'.

            prompt (str): User command line prompt
            default (scalar): Default value
            type (str): Expected value type. Must be one of 'text', 'int',
                'float', 'bool', 'url', 'location', or 'date'. Default: 'text'.

            field (str): Attribute to assign parsed content (default: content)

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
        ...     callback = lambda x: print(next(x))
        ...     conf = {'prompt': 'How old are you?', 'type': 'int'}
        ...     d = async_pipe(conf=conf, inputs={'content': '30'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        30
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> ComplexArg:
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

            field (str): Attribute to assign parsed content (default: content)

        inputs (dict): values to be used in place of prompting the user e.g.
            {'name': 'value1'}

        test (bool): Take input values from default (skip the console prompt)
        verbose (bool): Show debug messages when running pipe

    Yields:
       dict: item of user input

    Examples:
        >>> # int
        >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
        >>> next(pipe(conf=conf, inputs={'content': '30'}))
        30
        >>> next(pipe(conf=conf, inputs={'content': '30'}, emit=False))
        {'content': 30}

        >>> # date
        >>> import datetime
        >>> from datetime import datetime as dt, UTC
        >>> now = dt.now(UTC)
        >>>
        >>> conf = {'prompt': 'When were you born?', 'type': 'date'}
        >>> next(pipe(conf=conf, inputs={'content': '5/4/82'})).year
        1982
        >>> stream = pipe(conf={'type': 'date'}, inputs={'content': 'tomorrow'})
        >>> next(stream) > now.date()
        True

        >>> # float, bool, text
        >>> matrix = [
        ...     ('float', '1', 1.0),
        ...     ('bool', 'true', True),
        ...     ('text', 'hello', 'hello')]
        >>>
        >>> for t, c, r in matrix:
        ...     kwargs = {'conf': {'type': t}, 'inputs': {'content': c}}
        ...     next(pipe(**kwargs))
        1.0
        True
        'hello'

        >>> # url
        >>> inputs = {'content': 'google.com'}
        >>> next(pipe(conf={'type': 'url'}, inputs=inputs))
        'http://google.com'

        >>> # location
        >>> inputs = {'content': 'palo alto, ca'}
        >>> result = next(pipe(conf={'type': 'location'}, inputs=inputs))
        >>> sorted(result)[:5]
        ['admin1', 'admin2', 'admin3', 'city', 'country']
        >>> result['city']
        'city'
    """
    return parser(*args, **kwargs)
