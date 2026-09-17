"""General iterable composition, fan-out, selection, and deduplication helpers."""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from itertools import chain, dropwhile, takewhile
from typing import overload


def noop[T](item: T) -> T:
    """
    Passes an item through unchanged.

    Args:

        item: Value to pass through.

    Returns:

        The original ``item``.

    Examples:

        >>> noop({"value": 1})
        {'value': 1}

    """
    return item


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

           /--> item --> len(item) ----------> \
          /                                     \
    item -----> item --> str.upper(item) ---->  split
          \                                     /
           \--> item --> sorted(item) --------> /

    Args:

        item: The value passed to every function.
        funcs: The functions applied to ``item``.
        kwargs: Extra keyword arguments forwarded to each function.

    Returns:

        The result of each function, in order.

    Examples:

        >>> broadcast("bar", len, str.upper, sorted)
        (3, 'BAR', ['a', 'b', 'r'])

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
