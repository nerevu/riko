# vim: sw=4:ts=4:expandtab
"""
riko._iterutils
~~~~~~~~~~~~~~~
Functional/iterable helpers: fan-out (``dispatch``/``broadcast``), grouping,
dedup, chainable retry binding, and sort-key construction.
"""

import builtins
import itertools
from collections import defaultdict
from collections.abc import (
    Callable,
    ItemsView,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from decimal import Decimal
from functools import partial
from inspect import signature
from itertools import chain, dropwhile, repeat, takewhile
from logging import Logger
from math import isnan
from time import struct_time
from typing import Any, Literal, TypeVar, cast, overload

import pygogo as gogo
from requests.structures import CaseInsensitiveDict

from riko.cast import CAST_SWITCH, CastType, cast_value
from riko.types.general import Function
from riko.types.values import PrimitiveValue, PrimitiveValueType, SortableValue

logger: Logger = gogo.Gogo(__name__, monolog=True).logger
NON_SORTABLE = (Mapping, Sequence)

B = TypeVar("B", Literal[True], Literal[False])
T = TypeVar("T")

noop: Callable[[T], T] = lambda item: item


class Chainable:
    data: object
    method: Function | None
    list: builtins.list[object]

    def __init__(self, data: object, method: Function | None = None) -> None:
        self.data = data
        self.method = method
        self.list = listize(data)

    def __getattr__(self, name: str) -> "Chainable":
        funcs = (partial(getattr, x) for x in [self.data, builtins, itertools])
        zipped = zip(funcs, repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args: Any, **kwargs: object) -> "Chainable":
        method = self.method

        if method is None:
            result = Chainable(self.data)
        else:
            try:
                signature(method).bind(self.data, *args, **kwargs)
                data_first = True
            except TypeError:
                data_first = False
            except ValueError:
                data_first = True

            if data_first or not args:
                result = Chainable(method(self.data, *args, **kwargs))
            else:
                result = Chainable(method(args[0], self.data, **kwargs))

        return result


def invert_dict[K, V](d: dict[K, V]) -> dict[V, K]:
    return {v: k for k, v in d.items()}


def multi_try[T, S](
    source: object,
    zipped: Iterable[tuple[Callable[..., T], type[Exception]]],
    default: S = None,
) -> T | S:
    for func, error in zipped:
        try:
            value = func(source)
        except error:
            pass
        else:
            break
    else:
        value = default

    return value


def _resolve_uncastable(
    value: Mapping | Sequence | PrimitiveValue,
    msg: str,
    default: SortableValue,
) -> SortableValue | None:
    if isinstance(value, (str, int, struct_time)):
        msg += ". Returning value without casting."
        logger.warning(msg)
        casted = value
    elif isinstance(value, (dict, CaseInsensitiveDict, list, tuple, Mapping, Sequence)):
        msg += ". Returning default value."
        logger.warning(msg)
        casted = default
    else:
        msg += ". Returning value without casting."
        logger.warning(msg)
        casted = value

    return casted


def _warn_and_default(type_name: str, default: SortableValue) -> SortableValue:
    msg = f"Received non-sortable {type_name} value. Returning default instead."
    logger.warning(msg)
    return default


def _resolve_default(
    type_: str | None, invalid_type: bool | None, default: PrimitiveValue | None
) -> SortableValue:
    resolved = ""

    if invalid_type and default is None:
        logger.warning(f"Invalid cast type={type_}. Setting default to empty string.")
    elif type_ and default is None:
        _default = CAST_SWITCH[type_].get("default")
        resolved = cast(SortableValue, _default) if _default is not None else ""
    elif isinstance(default, Mapping):
        logger.warning(f"Invalid {default=}. Setting to empty string.")
    elif default is not None:
        resolved = default

    return resolved


def def_itemgetter(
    attr: str, default: PrimitiveValue | None = None, type_: str | None = None
) -> Callable[[Mapping | PrimitiveValue], SortableValue]:
    """
    Like operator.itemgetter but fills in missing keys with a typed default.

    Examples:
        >>> keyfunc = def_itemgetter('n', type_='int')
        >>> keyfunc({'n': 5})
        5
        >>> keyfunc({})
        0

    """
    _invalid_def_type = type_ in {CastType.LOCATION, CastType.NONE}
    invalid_def_type = bool(_invalid_def_type or (type_ and type_ not in CAST_SWITCH))
    default = _resolve_default(type_, invalid_def_type, default)

    _invalid_type = type_ in {CastType.LOCATION, CastType.PASS, CastType.NONE}
    invalid_type = _invalid_type or (type_ and type_ not in CAST_SWITCH)

    def keyfunc(item: Mapping | PrimitiveValue) -> SortableValue:
        if isinstance(item, (dict, CaseInsensitiveDict, Mapping)):
            value = item.get(attr, default)
        else:
            value = item

        msg = f"Invalid cast type={type_} for key '{attr}'."

        if invalid_type:
            casted = _resolve_uncastable(value, msg, default)
        elif type_:
            _casted = cast_value(value, CastType(type_))
            casted = cast(PrimitiveValue, _casted)
        elif isinstance(value, (str, int, struct_time)):
            casted = value
        elif isinstance(value, NON_SORTABLE):
            casted = _warn_and_default(type(value).__name__, default)
        elif value is not None:
            casted = value
        else:
            casted = default

        if casted is None or (isinstance(casted, (float, Decimal)) and isnan(casted)):
            casted = default

        return casted

    return keyfunc


# TODO: move this to meza.process.group
def group_by[T: Mapping | PrimitiveValue](
    content: Iterable[T], attr: str, default: PrimitiveValue | None = None
) -> ItemsView[str, list[T]]:
    keyfunc = def_itemgetter(attr, default)
    groups = defaultdict(list)

    for item in content:
        key = str(keyfunc(item))
        groups[key].append(item)

    return groups.items()


@overload
def unique_everseen[T](content: Iterable[T]) -> Iterator[T]: ...  # noqa: E704
@overload  # noqa: E302
def unique_everseen[T](  # noqa: E704
    content: Iterable[T], keyfunc: Callable
) -> Iterator[str]: ...
def unique_everseen[T](  # noqa: E302
    content: Iterable[T], keyfunc: Callable | None = None
) -> Iterator[str | T]:
    # List unique elements, preserving order. Remember all elements ever seen
    # unique_everseen('ABBcCaD', str.lower) --> a b c d
    seen = set()

    for element in content:
        k = str(keyfunc(element)) if keyfunc else element

        if k not in seen:
            seen.add(k)
            yield k


def betwix[T](
    iterable: Iterable[T],
    start: str | None = None,
    stop: str | None = None,
    inc: bool = False,
) -> Iterator[T]:
    """
    Extract selected elements from an iterable. But unlike `islice`,
    extract based on the element's value instead of its position.

    Args:
        iterable (iter): The initial sequence
        start (str): The fragment to begin with (inclusive)
        stop (str): The fragment to finish at (exclusive)
        inc (bool): Make stop operate inclusively (useful if reading a file and
            the start and stop fragments are on the same line)

    Returns:
        Iter: New dict with specified keys removed

    Examples:
        >>> from io import StringIO
        >>>
        >>> list(betwix('ABCDEFG', stop='C'))
        ['A', 'B']
        >>> list(betwix('ABCDEFG', 'C', 'E'))
        ['C', 'D']
        >>> list(betwix('ABCDEFG', 'C'))
        ['C', 'D', 'E', 'F', 'G']
        >>> f = StringIO('alpha\\n<beta>\\ngamma\\n')
        >>> list(betwix(f, '<', '>', True))
        ['<beta>\\n']
        >>> list(betwix('ABCDEFG', 'C', 'E', True))
        ['C', 'D', 'E']

    """

    def inc_takewhile(
        predicate: Callable[[T], bool], _iter: Iterable[T]
    ) -> Iterator[T]:
        for x in _iter:
            yield x

            if not predicate(x):
                break

    get_pred = lambda sentinel: lambda x: sentinel not in x
    pred = get_pred(stop)
    first = dropwhile(get_pred(start), iterable) if start else iterable

    if stop and inc:
        last: Iterator[T] = inc_takewhile(pred, first)
    elif stop:
        last = takewhile(pred, first)
    else:
        last = iter(first)

    return last


def dispatch[T, VT](split: Sequence[VT], *funcs: Callable[[VT], T]) -> tuple[T, ...]:
    r"""
    Takes a tuple of items and delivers each one to a different function

    Differs from `map` which applies multiple items to the same function.

           /--> item1 --> double(item1) -----> \
          /                                     \
    split ----> item2 --> oct(item2) ------->   _OUTPUT
          \                                     /
           \--> item3 --> max(item3) --------> /

    One way to construct such a flow in code would be::

    Example:
    >>> split = (3, 8365641317588141140, ['a', 'b', 'r'])
    >>> double = lambda item: item * 2
    >>> _OUTPUT = dispatch(split, double, oct, max)
    >>> _OUTPUT
    (6, '0o720305647221513002124', 'r')

    """
    # split = list(split)
    # for item, func in zip(split, funcs):
    #     v = func(item)
    #     print(f"dispatch: {func}({item}) = {v}")

    return tuple(func(item) for item, func in zip(split, funcs, strict=False))


def broadcast[T, VT](
    item: VT, *funcs: Callable[[VT], T], **kwargs: object
) -> tuple[T, ...]:
    r"""
    Delivers the same item to different functions.

    Differs from `map` which applies multiple items to the same function.

           /--> item --> len(item) --------> \
          /                                   \
    item -----> item --> hash(item) ------->  split
          \                                   /
           \--> item --> sorted(item) -----> /

    One way to construct such a flow in code would be::

    Example:
    >>> split = broadcast('bar', len, hash, sorted)
    >>> split
    (3, -6516517828960271057, ['a', 'b', 'r'])

    """
    return tuple(func(item, **kwargs) for func in funcs)


def multiplex[T](sources: Iterable[Iterable[T]]) -> Iterable[T]:
    """Combine multiple generators into one"""
    return chain.from_iterable(sources)


def select_by_id[T](
    _result: Iterable[Mapping[str, T]], _id: T, id_field: str
) -> Mapping[str, T]:
    try:
        result = next(r for r in _result if _id == r[id_field])
    except StopIteration:
        result = {}

    return result


# TODO: move back to meza
@overload
def listize[T](value: list[T]) -> list[T]: ...  # noqa: E704
@overload  # noqa: E302
def listize[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: dict[str, T],
) -> list[dict[str, T]]: ...
@overload  # noqa: E302
def listize[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: CaseInsensitiveDict[T],
) -> list[CaseInsensitiveDict[T]]: ...
@overload
def listize[T](value: Mapping[str, T]) -> list[Mapping[str, T]]: ...  # noqa: E704
@overload  # noqa: E302
def listize[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: Sequence[T],
) -> Sequence[T]: ...
@overload
def listize[T](value: Iterable[T]) -> Iterable[T]: ...  # noqa: E704
@overload
def listize[T](value: T) -> list[T]: ...  # noqa: E704
def listize[T](value: T) -> T | Iterable[T]:  # noqa: E302
    """
    Create a listlike object from any value

    Args:
        value: The object to convert

    Returns:
        value as a listlike object (wrapped in a list or the value itself)

    Examples:
    >>> listize(x for x in range(3))  # doctest: +ELLIPSIS
    <generator object <genexpr> at 0x...>
    >>> listize([x for x in range(3)])
    [0, 1, 2]
    >>> listize(iter(x for x in range(3)))  # doctest: +ELLIPSIS
    <generator object <genexpr> at 0x...>
    >>> listize(range(3))
    range(0, 3)
    >>> listize(0)
    [0]
    >>> listize(False)
    [False]
    >>> listize("")
    ['']
    >>> listize(None)
    []

    """
    if value is None:
        result = []
    elif isinstance(value, (PrimitiveValueType, dict, CaseInsensitiveDict, Mapping)):
        result = [value]
    elif isinstance(value, (Iterable, Sequence)):
        result = value
    else:
        result = [value]

    return result
