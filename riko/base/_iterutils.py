"""General iterable composition, fan-out, interleaving, and deduplication helpers."""

from __future__ import annotations

from functools import partial
from itertools import cycle, dropwhile, islice, takewhile
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator


def gen_instances[T](
    items: Iterable[object], accepted: type[T] | tuple[type[T], ...]
) -> Iterator[T]:
    """
    Generates the items that are instances of ``accepted``.

    Args:

        items: The source iterable.
        accepted: The type, or tuple of types, an item must be an instance of.

    Yields:

        Each item that is an instance of ``accepted``.

    Examples:

        >>> list(gen_instances([1, "a", 2.0, None], (int, float)))
        [1, 2.0]

    """
    return (item for item in items if isinstance(item, accepted))


@overload
def unique_everseen[T](content: Iterable[T]) -> Iterator[T]: ...
@overload
def unique_everseen[T](
    content: Iterable[T], keyfunc: Callable[[T], object]
) -> Iterator[T]: ...
def unique_everseen[T](
    content: Iterable[T], keyfunc: Callable[[T], object] | None = None
) -> Iterator[T]:
    """
    Deduplicates elements while preserving first-seen order.

    With ``keyfunc``, two elements are duplicates when their stringified keys match;
    without it, when the elements themselves match.

    Args:

        content: The source iterable.
        keyfunc: Optional function producing a uniqueness key per element.

    Yields:

        Each element the first time its key is seen.

    Examples:

        >>> list(unique_everseen("ABBcCaD", str.lower))
        ['A', 'B', 'c', 'D']
        >>> list(unique_everseen([1, 1, 2, 3, 2]))
        [1, 2, 3]

    """
    seen: set[object] = set()

    for element in content:
        key = element if keyfunc is None else str(keyfunc(element))

        if key not in seen:
            seen.add(key)
            yield element


@overload
def gen_non_none[T](value: Iterable[T | None]) -> Iterator[T]: ...
@overload
def gen_non_none[T, R](
    value: Iterable[T | None], func: Callable[[T], R]
) -> Iterator[R]: ...
def gen_non_none[T, R](
    value: Iterable[T | None], func: Callable[[T], R] | None = None
) -> Iterator[T | R]:
    """
    Applies a function to each non-None value in an iterable.

    Args:

        value: The source iterable.
        func: Optional function applied to each non-None element.

    Yields:

        Each non-None element, or ``func``'s result for it.

    Examples:

        >>> list(gen_non_none([1, None, 0, 2]))
        [1, 0, 2]
        >>> "".join(gen_non_none(["a", None, 1], str))
        'a1'

    """
    for item in value:
        if item is not None:
            yield item if func is None else func(item)


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


def partition[T](
    values: Iterable[T], predicate: Callable[[T], bool] | None = None
) -> tuple[list[T], list[T]]:
    """
    Splits an iterable into matching and non-matching lists by a predicate.

    Args:

        values: The source iterable.
        predicate: The test applied to each element; defaults to truthiness.

    Returns:

        A ``(matching, non_matching)`` pair of lists, each preserving order.

    Examples:

        >>> partition([1, 2, 3, 4], lambda n: n % 2 == 0)
        ([2, 4], [1, 3])
        >>> partition([0, 1, "", "x"])
        ([1, 'x'], [0, ''])

    """
    matching: list[T] = []
    non_matching: list[T] = []
    test = bool if predicate is None else predicate

    for item in values:
        (matching if test(item) else non_matching).append(item)

    return matching, non_matching


def sort_stably[T](items: Iterable[T]) -> list[T]:
    """
    Sorts items in an order that does not depend on hash randomization.

    Items that cannot be compared with each other, such as a mix of types, are
    sorted by their ``repr`` instead.

    Args:

        items: The items to sort, such as a set.

    Returns:

        The items in a stable order.

    Examples:

        >>> sort_stably({"b", "a"})
        ['a', 'b']
        >>> sort_stably({1, "a"})
        ['a', 1]

    """
    listed = list(items)

    try:
        result = sorted(listed)  # pyright: ignore[reportArgumentType]
    except TypeError:
        result = sorted(listed, key=repr)

    return result


def unzip[T, U](pairs: Iterable[tuple[T, U]]) -> tuple[list[T], list[U]]:
    """
    Splits pairs into a list of first elements and a list of second elements.

    Args:

        pairs: The pairs to split.

    Returns:

        The first elements and the second elements, each in input order.

    Examples:

        >>> unzip([("a", 1), ("b", 2)])
        (['a', 'b'], [1, 2])
        >>> unzip([])
        ([], [])

    """
    left: list[T] = []
    right: list[U] = []

    for a, b in pairs:
        left.append(a)
        right.append(b)

    return left, right


def multiplex[T](sources: Iterable[Iterable[T]]) -> Iterator[T]:
    """
    Interleaves multiple iterables into a single stream, round-robin.

    Args:

        sources: The iterables to interleave.

    Yields:

        One element from each iterable in turn, skipping each iterable once it is
        exhausted, until all are exhausted.

    Examples:

        >>> list(multiplex([[1, 2, 3], "ab"]))
        [1, 'a', 2, 'b', 3]

    """
    iterators = [iter(source) for source in sources]
    active = len(iterators)
    nexts = cycle(partial(next, iterator) for iterator in iterators)

    while active:
        try:
            for get_next in nexts:
                yield get_next()
        except StopIteration:
            active -= 1
            nexts = cycle(islice(nexts, active))
