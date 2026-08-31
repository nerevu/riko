# vim: sw=4:ts=4:expandtab
"""
Filters (includes or excludes) items from a stream.

With filter you create rules that compare item elements to values you specify.
So, for example, you may create a rule that says "permit items where the
item.description contains 'kittens'". Or a rule that says "omit any items where
the item.y:published is before yesterday".

A single filter module can contain multiple rules. You can choose whether those
rules will permit or block items that match those rules. Finally, you can choose
whether an item must match all the rules, or if it can just match any rule.

Lazy: items are tested and yielded one at a time.

Examples:
    Basic usage::

        >>> from riko.modules.filter import pipe
        >>>
        >>> items = ({"x": x} for x in range(5))
        >>> rule = {"field": "x", "op": "is", "value": 3}
        >>> next(pipe(items, conf={"rule": rule}))
        {'x': 3}

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

import operator as op
import re
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from logging import Logger
from typing import Any

import pygogo as gogo
from dateutil.parser import ParserError

from riko._objectify import Objectify
from riko._serialize import repr_cache
from riko.cast import cast_date
from riko.dotdict import DotDict
from riko.types._guards import is_mapping
from riko.types._options import Defaults, Opts
from riko.types._streams import Item, Stream
from riko.types._wrappers import PipeTuples
from riko.types.modules import FilterConfRule

from . import operator

OPTS: Opts = {"listize": True, "extract": "rule"}
DEFAULTS: Defaults = {"combine": "and", "permit": True, "stop": False}
COMBINE_BOOLEAN = {"and": all, "or": any}

SWITCH: dict[str, Callable[..., bool]] = {
    # TODO: add support for all containment semantics
    # 2 in [1, 2, 3]  or "a" in {"a": 1}
    "contains": lambda x, y: x and y.lower() in x.lower(),
    "doesnotcontain": lambda x, y: x and y.lower() not in x.lower(),
    "matches": lambda x, y: re.search(y, x),
    "eq": op.eq,
    "is": op.eq,
    "isnot": op.ne,
    "truthy": bool,
    "falsy": op.not_,
    "greater": op.gt,
    "after": op.gt,
    "atleast": op.ge,
    "less": op.lt,
    "before": op.lt,
    "atmost": op.le,
}

NUMERIC_OPS = {"atmost", "atleast"}
STRING_OPS = {"contains", "doesnotcontain", "matches"}
DATE_OPS = {"after", "before"}
PASSTHROUGH_OPS = {"truthy", "falsy", "eq", "is", "isnot"}
TRUTHINESS_OPS = {"truthy", "falsy"}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _parse_arg_uncached[VT](arg: VT, op: str) -> str | date | Decimal | VT | None:
    if op in PASSTHROUGH_OPS:
        value = arg
    elif op in STRING_OPS:
        value = str(arg)
    elif op in DATE_OPS:
        try:
            value = cast_date(arg)  # pyright: ignore[reportArgumentType]
        except (IndexError, ParserError, KeyError):
            value = None
    elif op in NUMERIC_OPS or isinstance(arg, (int, float)):
        if isinstance(arg, Decimal):
            value = arg
        elif isinstance(arg, int):
            value = Decimal(arg)
        elif isinstance(arg, float):
            value = Decimal(str(arg))
        else:
            try:
                value = Decimal(arg)  # pyright: ignore[reportArgumentType]
            except (InvalidOperation, ValueError):
                value = None
    else:
        value = arg

    return value


@repr_cache
def _parse_arg_cached[VT](arg: VT, op: str) -> str | date | Decimal | VT | None:
    return _parse_arg_uncached(arg, op)


def parse_arg[VT](
    arg: VT, op: str, memoize: bool = False
) -> str | date | Decimal | VT | None:
    func = _parse_arg_cached if memoize else _parse_arg_uncached
    return func(arg, op)


def parse_rule(rule: FilterConfRule, item: Item, **kwargs: object) -> bool:
    """
    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> numeric = Objectify({"field": "x", "op": "atleast", "value": 3})
        >>> parse_rule(numeric, {"x": 5})
        True
        >>> parse_rule(numeric, {})
        False
        >>> unknown = Objectify({"field": "x", "op": "bogus", "value": 3})
        >>> parse_rule(unknown, {"x": 5})
        False

    """
    truthiness = rule.op in TRUTHINESS_OPS
    _y = rule.value

    if isinstance(item, Objectify):
        _x = getattr(item, rule.field)
    elif is_mapping(item):
        _x = DotDict.dictize(item).get(rule.field, **kwargs)
    else:
        raise TypeError(f"Item is not a mapping: {item!r}.")

    has_value = _y is not None
    result = False

    if has_value and not truthiness:
        try:
            x = parse_arg(_x, rule.op)
            y = parse_arg(_y, rule.op, memoize=True)
        except (AttributeError, TypeError, ValueError, InvalidOperation, ParserError):
            x = y = None
    else:
        x, y = _x, _y

    has_value = y is not None
    operation = SWITCH.get(rule.op)

    if operation is None:
        logger.error(f"Unsupported filter operation: {rule.op!r}.")
    elif truthiness:
        result = operation(x)
    elif has_value and not (x is None or y is None):
        try:
            result = operation(x, y)
        except (AttributeError, TypeError, ValueError, InvalidOperation, ParserError):
            pass

    return result


def parser(
    _: Stream, extract: Sequence[FilterConfRule], tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Yields the items that match (or fail to match) every rule.

    Each rule's ``op`` is validated once up front, so an unsupported operation
    raises before any item is read.

    Args:
        _: The source. Unused; items are read from `tuples` instead.

        extract: The item independent rules.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Yields:
        Each item for which the combined rules match, or fail to match when
        ``permit`` is False.

    Raises:
        ValueError: If a rule names an unsupported ``op``.

    Examples:
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> conf = {"permit": True, "combine": "and"}
        >>> kwargs = {"conf": conf}
        >>> rule = {"field": "ex", "op": "greater", "value": 3}
        >>> objconf = Objectify(conf)
        >>> objrule = Objectify(rule)
        >>> stream = ({"ex": x} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> next(parser(stream, [objrule], tuples, **kwargs))
        {'ex': 4}
        >>> bad = Objectify({"field": "ex", "op": "bogus", "value": 3})
        >>> stream = ({"ex": x} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> next(parser(stream, [bad], tuples, **kwargs))
        Traceback (most recent call last):
            ...
        ValueError: Unsupported filter operation: 'bogus'.

    """
    for rule in extract:
        if rule.op not in SWITCH:
            raise ValueError(f"Unsupported filter operation: {rule.op!r}.")

        truthiness = rule.op in TRUTHINESS_OPS
        has_value = rule.value is not None

        if has_value and not truthiness:
            parse_arg(rule.value, rule.op, memoize=True)

    for item, objconf in tuples:
        try:
            func = COMBINE_BOOLEAN[objconf.combine]
        except KeyError:
            msg = f"Invalid combine: '{objconf.combine}'. (Expected 'and' or 'or')"
            logger.error(msg)
        else:
            result = func(parse_rule(rule, item, **kwargs) for rule in extract)

            if (result and objconf.permit) or not (result or objconf.permit):
                yield item
            elif objconf.stop:
                break


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously filters a stream to the items matching the given rules.

    Lazy: items are tested and yielded one at a time.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The filter criteria. Required.

                field (str): The item field to search.

                op (str): The comparison, one of "contains", "doesnotcontain",
                    "matches", "eq", "is", "isnot", "truthy", "falsy",
                    "greater", "after", "atleast", "less", "before", "atmost".

                value (scalar): The value to compare the item's field to.

            permit (bool): Whether to yield the matches rather than the
                non-matches (default: True).

            combine (str): How to interpret multiple rules, either "and" (all
                rules must pass) or "or" (any rule must pass) (default: "and").

            stop (bool): Whether to stop at the first item that fails. Later
                items are dropped even if they would match (default: False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "filter").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.
        ValueError: If a rule names an unsupported ``op``.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = [{"title": "Good job!"}, {"title": "Website Developer"}]
        ...     rule = {"field": "title", "op": "contains", "value": "web"}
        ...     result = await async_pipe(items, conf={"rule": rule})
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        Website Developer

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Filters a stream to the items matching the given rules.

    Lazy: items are tested and yielded one at a time.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The filter criteria. Required.

                field (str): The item field to search.

                op (str): The comparison, one of "contains", "doesnotcontain",
                    "matches", "eq", "is", "isnot", "truthy", "falsy",
                    "greater", "after", "atleast", "less", "before", "atmost".

                value (scalar): The value to compare the item's field to.

            permit (bool): Whether to yield the matches rather than the
                non-matches (default: True).

            combine (str): How to interpret multiple rules, either "and" (all
                rules must pass) or "or" (any rule must pass) (default: "and").

            stop (bool): Whether to stop at the first item that fails. Later
                items are dropped even if they would match (default: False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "filter").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.
        ValueError: If a rule names an unsupported ``op``.

    Examples:
        >>> items = [{"title": "Good job!"}, {"title": "Website Developer"}]
        >>> rule = {"field": "title", "op": "contains", "value": "web"}
        >>> next(pipe(items, conf={"rule": rule}))
        {'title': 'Website Developer'}
        >>> rule["value"] = "kjhlked"
        >>> any(pipe(items, conf={"rule": [rule]}))
        False
        >>> items = ({"x": x} for x in range(5))
        >>> rule = {"field": "x", "op": "less", "value": 2}
        >>> result = pipe(items, conf={"rule": rule, "stop": True})
        >>> len(list(result))
        2

    """
    return parser(*args, **kwargs)
