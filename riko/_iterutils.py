# vim: sw=4:ts=4:expandtab
"""
riko._iterutils
~~~~~~~~~~~~~~~

Functional/iterable helpers: fan-out (``dispatch``/``broadcast``), grouping,
dedup, chainable retry binding, and sort-key construction.

Attributes:
    SORT_FILLER: Orderable stand-in (``-inf``) for a missing sort key.
    DATELIKE_TYPES: Cast types reduced to epoch timestamps for sorting.
    INVALID_DEF_TYPES: Cast types with no usable typed default.
    INVALID_TYPES: Cast types that cannot be cast at all.
    NON_SORTABLE: Types (mappings, sequences) that fall back to the default key.
    noop: Identity function returning its argument unchanged.

"""

import builtins
import itertools
from collections import defaultdict
from collections.abc import Callable, ItemsView, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, date, tzinfo
from datetime import datetime as dt
from decimal import Decimal
from functools import partial
from inspect import signature
from itertools import chain, dropwhile, repeat, takewhile
from logging import Logger
from math import isnan
from time import struct_time
from typing import Any, Literal, TypeGuard, TypeVar, cast, overload

import pygogo as gogo
from requests.structures import CaseInsensitiveDict

from riko._date_utils import date_to_datetime, ensure_tzinfo
from riko.cast import CAST_SWITCH, CastType, cast_value
from riko.types._scalars import PrimitiveValue, PrimitiveValueType, SortableValue
from riko.types._streams import Item

logger: Logger = gogo.Gogo(__name__, monolog=True).logger
SORT_FILLER = float("-inf")
DATELIKE_TYPES = frozenset({CastType.DATE, CastType.DATETIME})
INVALID_DEF_TYPES = frozenset({CastType.LOCATION, CastType.NONE})
INVALID_TYPES = frozenset({CastType.LOCATION, CastType.PASS, CastType.NONE})

NON_SORTABLE = (Mapping, Sequence)

B = TypeVar("B", Literal[True], Literal[False])
T = TypeVar("T")

noop: Callable[[T], T] = lambda item: item


class Chainable:
    """
    A fluent wrapper that resolves and applies methods across namespaces.

    Attribute access looks the name up on the wrapped data, then ``builtins``,
    then ``itertools``, and returns a new ``Chainable`` bound to the found method.
    Calling it applies the method with the data as the first argument when the
    method's signature accepts it there, else as the second.

    Examples:
        >>> Chainable([3, 1, 2]).sorted().data
        [1, 2, 3]

    """

    data: object
    method: Callable | None
    list: builtins.list[object]

    def __init__(self, data: object, method: Callable | None = None) -> None:
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
    """
    Swaps a dict's keys and values.

    Args:
        d: The dict to invert; its values must be hashable and unique.

    Returns:
        A new dict mapping each value back to its key.

    Examples:
        >>> invert_dict({"a": 1, "b": 2})
        {1: 'a', 2: 'b'}

    """
    return {v: k for k, v in d.items()}


def multi_try[T, S](
    source: object,
    zipped: Iterable[tuple[Callable[..., T], type[Exception]]],
    default: S = None,
) -> T | S:
    """
    Tries each callable on a source until one does not raise.

    Each entry pairs a callable with the exception type to swallow for it; the
    first call that avoids its paired exception wins. When every attempt raises,
    ``default`` is returned.

    Args:
        source: The value passed to each callable.
        zipped: Pairs of ``(callable, exception_type)`` tried in order.
        default: The value returned when every attempt raises.

    Returns:
        The first successful result, or ``default`` if none succeed.

    Examples:
        >>> from itertools import repeat
        >>>
        >>> multi_try("abc", zip([int, str.upper], repeat(ValueError)))
        'ABC'
        >>> multi_try("abc", zip([int], repeat(ValueError)), default=-1)
        -1

    """
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
    value: Mapping | Sequence | PrimitiveValue, msg: str, default: SortableValue
) -> SortableValue | None:
    """
    Handles a value that cannot be cast for a sort key, degrading by type.

    A scalar (``str``/``int``/``struct_time``) is returned uncast since it is
    already orderable; a container is replaced with ``default``, which the caller
    supplies as an orderable filler. Every branch logs a warning rather than
    raising, so a heterogeneous feed still sorts.

    Args:
        value: The value that failed casting.
        msg: The warning prefix describing the failed cast.
        default: The orderable filler used for non-scalar values.

    Returns:
        The original value when it is already orderable, else ``default``.

    """
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
    """
    Resolves the sort-key default for a cast type, kept orderable.

    A cast default marks "no value" and may be non-orderable (``NaN`` for
    ``float``/``decimal``, ``None`` for dates). Those and all date-like types
    collapse to ``SORT_FILLER`` (``-inf``), which compares against real keys. A
    falsy-but-valid caller default (``0``/``False``) is preserved; only ``None``
    and a mapping default fall back to the empty string.

    Args:
        type_: The cast type name, or ``None`` for no casting.
        invalid_type: Whether ``type_`` has no usable typed default.
        default: The caller-supplied default, if any.

    Returns:
        An orderable default suitable as a sort-key filler.

    """
    resolved = ""

    if invalid_type and default is None:
        logger.warning(f"Invalid cast type={type_}. Setting default to empty string.")
    elif type_ and default is None:
        _default = CAST_SWITCH[type_].get("default")
        unorderable = isinstance(_default, (float, Decimal)) and isnan(_default)

        if unorderable or type_ in DATELIKE_TYPES:
            resolved = SORT_FILLER
        elif _default is not None:
            resolved = cast(SortableValue, _default)
    elif isinstance(default, Mapping):
        logger.warning(f"Invalid {default=}. Setting to empty string.")
    elif default is not None:
        resolved = default

    return resolved


def def_itemgetter(
    attr: str,
    default: PrimitiveValue | None = None,
    type_: str | None = None,
    fallback_tzinfo: tzinfo = UTC,
) -> Callable[[Mapping | PrimitiveValue], SortableValue]:
    """
    Like operator.itemgetter but fills in missing keys with a typed default.

    Args:
        attr: The key read from each item.
        default: The value used when the key is missing or uncastable.
        type_: Optional cast type applied to the value.
        fallback_tzinfo: Timezone assigned to naive datetimes before they are
            reduced to sortable timestamps.

    Returns:
        A key function mapping an item to a sortable value.

    Examples:
        >>> keyfunc = def_itemgetter("n", type_="int")
        >>> keyfunc({"n": 5})
        5
        >>> keyfunc({})
        0
        >>> # an invalid number sorts via -inf, not NaN
        >>> keyfunc = def_itemgetter("n", type_="float")
        >>> keyfunc({}), keyfunc({"n": "abc"})
        (-inf, -inf)

    """
    not_switch = type_ and type_ not in CAST_SWITCH
    invalid_def_type = bool((type_ in INVALID_DEF_TYPES) or not_switch)
    default = _resolve_default(type_, invalid_def_type, default)
    invalid_type = bool((type_ in INVALID_TYPES) or not_switch)

    def keyfunc(item: Mapping | PrimitiveValue) -> SortableValue:
        if isinstance(item, (dict, CaseInsensitiveDict, Mapping)):
            value = item.get(attr)
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

        if type_ in DATELIKE_TYPES and isinstance(casted, (date, dt)):
            if isinstance(casted, dt):
                aware = ensure_tzinfo(casted, fallback_tzinfo=fallback_tzinfo)
            else:
                aware = date_to_datetime(casted, fallback_tzinfo=fallback_tzinfo)

            casted = aware.timestamp()

        if casted is None or (isinstance(casted, (float, Decimal)) and isnan(casted)):
            casted = default

        return casted

    return keyfunc


# TODO: move this to meza.process.group
def group_by[T: Mapping | PrimitiveValue](
    content: Iterable[T], attr: str, default: PrimitiveValue | None = None
) -> ItemsView[str, list[T]]:
    """
    Groups items by the stringified value of a key.

    Args:
        content: The items to group.
        attr: The key read from each item.
        default: The value used when an item lacks ``attr``.

    Returns:
        A view of ``(key, items)`` pairs, one per distinct key.

    Examples:
        >>> items = [{"k": "a"}, {"k": "b"}, {"k": "a"}]
        >>> sorted((k, len(v)) for k, v in group_by(items, "k"))
        [('a', 2), ('b', 1)]

    """
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
    """
    Deduplicates elements while preserving first-seen order.

    With ``keyfunc``, uniqueness is by the stringified key and the key is yielded;
    without it, elements are yielded.

    Args:
        content: The source iterable.
        keyfunc: Optional function producing a uniqueness key per element.

    Yields:
        Each element (or its key) the first time it is seen.

    Examples:
        >>> list(unique_everseen("ABBcCaD", str.lower))
        ['a', 'b', 'c', 'd']
        >>> list(unique_everseen([1, 1, 2, 3, 2]))
        [1, 2, 3]

    """
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
    Extracts elements from an iterable by value rather than position.

    Unlike ``islice``, the bounds match on an element's value.

    Args:
        iterable: The initial sequence.
        start: The fragment to begin with (inclusive).
        stop: The fragment to finish at (exclusive).
        inc: Whether stop operates inclusively (useful if reading a file and
            the start and stop fragments are on the same line).

    Returns:
        The matching elements as an iterator.

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


@overload
def dispatch[T, U, X, Y](  # noqa: E704
    split: tuple[T, U],
    f1: Callable[[T], X],
    f2: Callable[[U], Y],
    /,  # stops ruff from collapsing this line
) -> tuple[X, Y]: ...
@overload  # noqa: E302
def dispatch[T, U, V, X, Y, Z](  # noqa: E704
    split: tuple[T, U, V],
    f1: Callable[[T], X],
    f2: Callable[[U], Y],
    f3: Callable[[V], Z],
    /,
) -> tuple[X, Y, Z]: ...
@overload  # noqa: E302
def dispatch[T](  # noqa: E704
    split: Sequence[T], *funcs: Callable[[T], object]
) -> tuple[object, ...]: ...
def dispatch(  # noqa: E302
    split: Sequence[object], *funcs: Callable[..., object]
) -> tuple[object, ...]:
    r"""
    Delivers each item of a sequence to a different function.

    Differs from ``map``, which applies multiple items to the same function::

           /--> item1 --> double(item1) -----> \
          /                                     \
    split ----> item2 --> oct(item2) -------->  _OUTPUT
          \                                     /
           \--> item3 --> max(item3) --------> /

    Args:
        split: The items to distribute.
        funcs: One function per item, applied positionally.

    Returns:
        The result of each function, in order.

    Examples:
        >>> split = (3, 8365641317588141140, ["a", "b", "r"])
        >>> double = lambda item: item * 2
        >>> dispatch(split, double, oct, max)
        (6, '0o720305647221513002124', 'r')

    """
    return tuple(func(item) for item, func in zip(split, funcs, strict=False))


@overload
def broadcast[W, X](  # noqa: E704
    item: object, f1: Callable[..., W], f2: Callable[..., X], **kwargs: object
) -> tuple[W, X]: ...
@overload  # noqa: E302
def broadcast[W, X, Y](  # noqa: E704
    item: object,
    f1: Callable[..., W],
    f2: Callable[..., X],
    f3: Callable[..., Y],
    **kwargs: object,
) -> tuple[W, X, Y]: ...
@overload  # noqa: E302
def broadcast[W, X, Y, Z](  # noqa: E704
    item: object,
    f1: Callable[..., W],
    f2: Callable[..., X],
    f3: Callable[..., Y],
    f4: Callable[..., Z],
    **kwargs: object,
) -> tuple[W, X, Y, Z]: ...
def broadcast(  # noqa: E302
    item: object, *funcs: Callable[..., object], **kwargs: object
) -> tuple[object, ...]:
    r"""
    Delivers the same item to different functions.

    Differs from ``map``, which applies multiple items to the same function::

           /--> item --> len(item) --------> \
          /                                   \
    item -----> item --> hash(item) ------->  split
          \                                   /
           \--> item --> sorted(item) -----> /

    Args:
        item: The value passed to every function.
        funcs: The functions applied to ``item``.
        kwargs: Extra keyword arguments forwarded to each function.

    Returns:
        The result of each function, in order.

    Examples:
        >>> broadcast("bar", len, hash, sorted)
        (3, -6516517828960271057, ['a', 'b', 'r'])

    """
    return tuple(func(item, **kwargs) for func in funcs)


def multiplex[T](sources: Iterable[Iterable[T]]) -> Iterable[T]:
    """
    Combines multiple iterables into a single stream.

    Args:
        sources: The iterables to chain together.

    Returns:
        A single iterator over every element, source by source.

    Examples:
        >>> list(multiplex([[1, 2], [3, 4]]))
        [1, 2, 3, 4]

    """
    return chain.from_iterable(sources)


def select_by_id[T](
    content: Iterable[Mapping[str, T]], id_: T, id_field: str
) -> Mapping[str, T]:
    """
    Finds the first mapping whose id field equals a target id.

    Args:
        content: The mappings to search.
        id_: The id value to match.
        id_field: The field holding each mapping's id.

    Returns:
        The first matching mapping, or an empty dict when none match.

    Examples:
        >>> rows = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]
        >>> select_by_id(rows, 2, "id")
        {'id': 2, 'v': 'b'}
        >>> select_by_id(rows, 9, "id")
        {}

    """
    try:
        result = next(r for r in content if id_ == r[id_field])
    except StopIteration:
        result = {}

    return result


def is_listlike[T](value: Iterable[T] | object) -> TypeGuard[Iterable[T]]:
    """
    Reports whether a value is listlike (a multi-item iterable).

    A listlike value is any iterable that is not a mapping, primitive, or ``None``.

    Args:
        value: The object to classify.

    Returns:
        True when ``value`` maps over items, False when it is one item.

    Examples:
        >>> is_listlike([1, 2])
        True
        >>> is_listlike((1, 2))
        True
        >>> is_listlike(iter([1, 2]))
        True
        >>> is_listlike(range(3))
        True
        >>> is_listlike({"a": 1})
        False
        >>> is_listlike("ab")
        False
        >>> is_listlike(0)
        False
        >>> is_listlike(None)
        False

    """
    if value is None or isinstance(
        value, (PrimitiveValueType, dict, CaseInsensitiveDict, Mapping)
    ):
        result = False
    else:
        result = isinstance(value, (Iterable, Sequence))

    return result


# TODO: move back to meza
@overload
def listize(  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: Item | Iterable[Item],
) -> Iterable[Item]: ...
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
    Creates a listlike object from any value.

    Args:
        value: The object to convert.

    Returns:
        ``value`` as a listlike object (wrapped in a list, or itself).

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
    elif is_listlike(value):
        result = value
    else:
        result = [value]

    return result
