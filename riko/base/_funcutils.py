from __future__ import annotations

from typing import TYPE_CHECKING, Concatenate, overload

from ._logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from logging import Logger

    from riko.types._wrappers import Func

logger: Logger = get_logger(__name__)


def multi_try[T, S](
    source: object, zipped: Iterable[tuple[Func[T], type[Exception]]], default: S = None
) -> T | S:
    """
    Tries each callable on a source until one does not raise.

    Each entry pairs a callable with the exception type to swallow for it; the
    first call that avoids its paired exception wins. When every attempt raises,
    ``default`` is returned.

    Args:

        source: The value passed to each callable.
        zipped: Pairs of ``(callable, exception_type)`` tried in order.

    Kwargs:

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


def noop[T](value: T) -> T:
    """
    Passes a value through unchanged.

    Args:

        value: Value to pass through.

    Returns:

        The original ``value``.

    Examples:

        >>> noop({"value": 1})
        {'value': 1}

    """
    return value


def map_values[K, V, R](
    func: Callable[[V], R],
    item: Mapping[K, V],
    non_null: bool = False,
    **kwargs: object,
) -> dict[K, R]:
    """
    Applies a function to each value of a mapping.

    Args:

        func: The transform applied to each value.
        item: The source mapping.

    Kwargs:

        non_null: Whether to drop the keys whose value is ``None`` instead of
            transforming them.

    Returns:

        A new dict with the same keys, in the same order, holding the
        transformed values.

    Examples:

        >>> map_values(len, {"a": "xy", "b": ""})
        {'a': 2, 'b': 0}
        >>> map_values(len, {"a": "xy", "b": None}, non_null=True)
        {'a': 2}

    """
    if non_null:
        result = {
            key: func(value, **kwargs)
            for key, value in item.items()
            if value is not None
        }
    else:
        result = {key: func(value, **kwargs) for key, value in item.items()}

    return result


def call_if_distinct[T, **P](
    func: Callable[Concatenate[T, P], object],
    value: T,
    other: object,
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> None:
    """
    Calls ``func`` with ``value`` unless ``value`` is ``other``.

    The test is identity, never equality.

    Args:

        func: Called with ``value`` and the remaining arguments.
        value: The first argument to ``func``.
        other: The object ``value`` must not be.
        *args: Positional arguments passed to ``func``.

    Kwargs:

        **kwargs: Keyword arguments passed to ``func``.

    Examples:

        >>> calls = []
        >>> source, stream = [1], iter([1])
        >>> call_if_distinct(calls.append, stream, stream)
        >>> calls
        []
        >>> call_if_distinct(calls.append, source, stream)
        >>> calls
        [[1]]

    """
    if value is not other:
        func(value, *args, **kwargs)


def map_keys[K, V, R](func: Callable[[K], R], item: Mapping[K, V]) -> dict[R, V]:
    """
    Applies a function to each key of a mapping.

    Args:

        func: The transform applied to each key.
        item: The source mapping.

    Returns:

        A new dict with the transformed keys, in the same order, holding the
        original values. When two keys transform to the same key, the later
        value wins.

    Examples:

        >>> map_keys(str.lower, {"A": 1, "b": 2})
        {'a': 1, 'b': 2}
        >>> map_keys(str.lower, {"A": 1, "a": 2})
        {'a': 2}

    """
    return {func(key): value for key, value in item.items()}


def map_keys_and_values[K, V, RK, RV](
    key_func: Callable[[K], RK],
    value_func: Callable[[V], RV],
    item: Mapping[K, V],
    non_null: bool = False,
) -> dict[RK, RV]:
    """
    Applies one function to each key of a mapping and another to each value.

    Args:

        key_func: The transform applied to each key.
        value_func: The transform applied to each value.
        item: The source mapping.

    Kwargs:

        non_null: Whether to drop the keys whose value is ``None`` instead of
            transforming them.

    Returns:

        A new dict with the transformed keys, in the same order, holding the
        transformed values. When two keys transform to the same key, the later
        value wins.

    Examples:

        >>> map_keys_and_values(str.lower, len, {"A": "xy", "b": ""})
        {'a': 2, 'b': 0}

    """
    if non_null:
        result = {key_func(k): value_func(v) for k, v in item.items() if v is not None}
    else:
        result = {key_func(key): value_func(value) for key, value in item.items()}

    return result


@overload
def dispatch[T, U, X, Y](
    split: tuple[T, U],
    f1: Callable[[T], X],
    f2: Callable[[U], Y],
    /,  # stops ruff from collapsing this line
) -> tuple[X, Y]: ...
@overload
def dispatch[T, U, V, X, Y, Z](
    split: tuple[T, U, V],
    f1: Callable[[T], X],
    f2: Callable[[U], Y],
    f3: Callable[[V], Z],
    /,
) -> tuple[X, Y, Z]: ...
@overload
def dispatch[T](
    split: Sequence[T], *funcs: Callable[[T], object]
) -> tuple[object, ...]: ...
def dispatch(split: Sequence[object], *funcs: Func[object]) -> tuple[object, ...]:
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

        The result of each function.

    Examples:

        >>> split = (3, 8365641317588141140, ["a", "b", "r"])
        >>> double = lambda item: item * 2
        >>> dispatch(split, double, oct, max)
        (6, '0o720305647221513002124', 'r')

    """
    return tuple(func(item) for item, func in zip(split, funcs, strict=False))


@overload
def broadcast[W, X](
    item: object, f1: Func[W], f2: Func[X], **kwargs: object
) -> tuple[W, X]: ...
@overload
def broadcast[W, X, Y](
    item: object, f1: Func[W], f2: Func[X], f3: Func[Y], **kwargs: object
) -> tuple[W, X, Y]: ...
@overload
def broadcast[W, X, Y, Z](
    item: object, f1: Func[W], f2: Func[X], f3: Func[Y], f4: Func[Z], **kwargs: object
) -> tuple[W, X, Y, Z]: ...
def broadcast(
    item: object, *funcs: Func[object], **kwargs: object
) -> tuple[object, ...]:
    r"""
    Delivers the same item to different functions.

    Differs from ``map``, which applies multiple items to the same function::

           /--> item --> len(item) ----------> \
          /                                     \
    item -----> item --> str.upper(item) ---->  split
          \                                     /
           \--> item --> sorted(item) -------> /

    Args:

        item: The value passed to every function.
        funcs: The functions applied to ``item``.

    Kwargs:

        kwargs: Extra keyword arguments forwarded to each function.

    Returns:

        The result of each function.

    Examples:

        >>> broadcast("bar", len, str.upper, sorted)
        (3, 'BAR', ['a', 'b', 'r'])

    """
    return tuple(func(item, **kwargs) for func in funcs)


def invert_dict[K, V](item: dict[K, V]) -> dict[V, K]:
    """
    Swaps a dict's keys and values.

    Args:

        item: The dict to invert; its values must be hashable and unique.

    Returns:

        A new dict mapping each value back to its key.

    Examples:

        >>> invert_dict({"a": 1, "b": 2})
        {1: 'a', 2: 'b'}

    """
    return {v: k for k, v in item.items()}


@overload
def resolve_default[K, V](
    value: Mapping[K, V], default: object = ..., fallback: None = ...
) -> Mapping[K, V]: ...
@overload
def resolve_default[K, V, F](value: Mapping[K, V], *, fallback: F) -> F: ...
@overload
def resolve_default[K, V, F](
    value: Mapping[K, V], default: object, fallback: F
) -> F: ...
@overload
def resolve_default[K, V](
    value: object, *, fallback: Mapping[K, V]
) -> Mapping[K, V]: ...
@overload
def resolve_default[K, V](
    value: object, default: None, fallback: Mapping[K, V]
) -> Mapping[K, V]: ...
@overload
def resolve_default(
    value: None, default: None = ..., fallback: object = ...
) -> dict[object, object]: ...
@overload
def resolve_default[D](value: None, default: D, fallback: object = ...) -> D: ...
@overload
def resolve_default[V](
    value: V | None, default: None = ..., fallback: None = ...
) -> V | dict[object, object]: ...
@overload
def resolve_default[V, D](
    value: V | None, default: D, fallback: None = ...
) -> V | D: ...
@overload
def resolve_default[V, F](
    value: object, *, fallback: F
) -> F | dict[object, object]: ...
@overload
def resolve_default[V, F](
    value: object, default: None, fallback: F
) -> F | dict[object, object]: ...
@overload
def resolve_default[V, D, F](value: object, default: D, fallback: F) -> D | F: ...
def resolve_default(
    value: object, default: object | None = None, fallback: object | None = None
) -> object:
    """
    Resolves ``default`` when ``value`` is None, else ``fallback``.

    Args:

        value: The value to test against None.

    Kwargs:

        default: The result when ``value`` is None (default: an empty dict).
        fallback: The result when ``value`` is present (``value`` when omitted).

    Returns:

        ``default`` or ``fallback``.

    Examples:

        >>> resolve_default(None)
        {}
        >>> resolve_default(0, 5)
        0
        >>> resolve_default(None, 5)
        5
        >>> resolve_default("ctx", "", "; context")
        '; context'

    """
    fallback = value if fallback is None else fallback
    default = {} if default is None else default
    return default if value is None else fallback
