# vim: sw=4:ts=4:expandtab
"""
Provides functions for performing simple mathematical operations, e.g.,
addition, subtraction, multiplication, division, modulo, averages, etc.

Examples:
    basic usage::

        >>> from decimal import Decimal
        >>> from riko.modules.simplemath import pipe
        >>>
        >>> conf = {'op': 'divide', 'other': '5'}
        >>> next(pipe({'content': '10'}, conf=conf))['simplemath']
        Decimal('2')

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import operator
from collections.abc import Callable
from decimal import Decimal

import pygogo as gogo

from riko.cast import BasicCastType, CastType, cast
from riko.types.configs import SimpleMathObjconf
from riko.types.general import Defaults, Extraction, NumLike, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.DECIMAL, "field": "content"}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def mean(*nums):
    try:
        return sum(nums) / len(nums)
    except ZeroDivisionError:
        return float("inf")


OPS: dict[str, Callable[..., NumLike]] = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "mean": mean,
    "divide": operator.truediv,
    "floor": operator.floordiv,
    "modulo": operator.mod,
    "power": operator.pow,
}


def parser(
    num: Decimal, extraction: Extraction, objconf: SimpleMathObjconf, **kwargs
) -> NumLike:
    """
    Parsers the pipe content

    Args:
        num (Decimal): The first number to operate on
        objconf (obj): The pipe configuration (an Objectify instance)

    Returns:
        dict: The formatted item

    Examples:
        >>> from meza.fntools import Objectify
        >>> conf = {'op': 'divide', 'other': 4}
        >>> objconf = Objectify(conf)
        >>> parser(10, None, objconf)
        Decimal('2.5')

    """
    operation = OPS[objconf.op]
    other = cast(objconf.other, _type=CastType.DECIMAL)
    return operation(num, other)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> NumLike:
    """
    A processor module that asynchronously performs basic arithmetic, such
    as addition and subtraction.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the keys 'other'
            and 'op'.

            other (number): The second number to operate on.
            op (str): The math operation. Must be one of 'addition',
                'subtraction', 'multiplication', 'division', 'modulo',
                'floor', 'power', or 'mean'.

        assign (str): Attribute to assign parsed content (default: simplemath)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
        Deferred: twisted.internet.defer.Deferred item with formatted currency

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     conf = {'op': 'divide', 'other': '5'}
        ...     result = await async_pipe({'content': '10'}, conf=conf)
        ...     print(next(result)['simplemath'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        2

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> NumLike:
    """
    A processor module that performs basic arithmetic, such as addition and
    subtraction.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the keys 'other'
            and 'op'.

            other (number): The second number to operate on.
            op (str): The math operation. Must be one of 'addition',
                'subtraction', 'multiplication', 'division', 'modulo',
                'floor', 'power', or 'mean'.

        assign (str): Attribute to assign parsed content (default: simplemath)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
        dict: an item with math result

    Examples:
        >>> from decimal import Decimal
        >>> conf = {'op': 'divide', 'other': '5'}
        >>> next(pipe({'content': '10'}, conf=conf))['simplemath']
        Decimal('2')
        >>> kwargs = {'conf': conf, 'field': 'num', 'assign': 'result'}
        >>> next(pipe({'num': '10'}, **kwargs))['result']
        Decimal('2')

    """
    return parser(*args, **kwargs)
