"""General iterable composition, fan-out, interleaving, and deduplication helpers."""

from __future__ import annotations

from functools import partial
from itertools import chain, cycle, dropwhile, islice, takewhile
from typing import TYPE_CHECKING, Literal, overload

from ._guards import is_known_sequence, is_mapping, require_sequence

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

    from riko.types._frozendict import SortKey
    from riko.types._wrappers import Func


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


def gen_nested_mappings(value: object) -> Iterator[Mapping[str, object]]:
    """
    Walks a nested value and emits every mapping in it.

    Args:

        value: The value to walk, such as a module configuration.

    Yields:

        Each mapping found, outermost first.

    Examples:

        >>> conf = {"rule": [{"field": "a"}, {"value": {"input": "q"}}]}
        >>> [sorted(found) for found in gen_nested_mappings(conf)]
        [['rule'], ['field'], ['value'], ['input']]

    """
    if is_mapping(value):
        yield value

        for child in value.values():
            yield from gen_nested_mappings(child)
    elif is_known_sequence(value):
        for child in value:
            yield from gen_nested_mappings(child)


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

    Kwargs:

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


def _get_value(
    item: object, pos: int | None, attr: str | None, msg: Func[str]
) -> object:
    if pos is not None:
        item = require_sequence(item, msg, error=TypeError)[pos]

    if item is not None and attr is not None:
        item = getattr(item, attr)

    return item


@overload
def gen_non_null[T, U](
    items: Iterable[tuple[T, U | None] | None],
    func: None = None,
    *,
    cmp_pos: Literal[1],
    arg_pos: Literal[0],
    cmp_attr: str | None = None,
    arg_attr: None = None,
) -> Iterator[T]: ...
@overload
def gen_non_null[T, U, R](
    items: Iterable[tuple[T, U | None] | None],
    func: Callable[[T], R],
    *,
    cmp_pos: Literal[1],
    arg_pos: Literal[0],
    cmp_attr: str | None = None,
    arg_attr: None = None,
) -> Iterator[R]: ...
@overload
def gen_non_null[T](
    items: Iterable[T | None],
    func: None = None,
    *,
    cmp_pos: int | None = None,
    arg_pos: None = None,
    cmp_attr: str | None = None,
    arg_attr: None = None,
) -> Iterator[T]: ...
@overload
def gen_non_null[T, R](
    items: Iterable[T | None],
    func: Callable[[T], R],
    *,
    cmp_pos: int | None = None,
    arg_pos: None = None,
    cmp_attr: str | None = None,
    arg_attr: None = None,
) -> Iterator[R]: ...
@overload
def gen_non_null[T](
    items: Iterable[Sequence[T] | None],
    func: None = None,
    *,
    cmp_pos: int | None = None,
    arg_pos: int = ...,
    cmp_attr: str | None = None,
    arg_attr: None = None,
) -> Iterator[T]: ...
@overload
def gen_non_null[T, R](
    items: Iterable[Sequence[T] | None],
    func: Callable[[T], R],
    *,
    cmp_pos: int | None = None,
    arg_pos: int = ...,
    cmp_attr: str | None = None,
    arg_attr: None = None,
) -> Iterator[R]: ...
@overload
def gen_non_null[T](
    items: Iterable[T | None],
    func: None = None,
    *,
    cmp_pos: int | None = None,
    arg_pos: int | None = None,
    cmp_attr: str | None = None,
    arg_attr: str,
) -> Iterator[object]: ...
@overload
def gen_non_null[T, R](
    items: Iterable[T | None],
    func: Func[R],
    *,
    cmp_pos: int | None = None,
    arg_pos: int | None = None,
    cmp_attr: str | None = None,
    arg_attr: str,
) -> Iterator[R]: ...
def gen_non_null(
    items: Iterable[object],
    func: Func[object] | None = None,
    *,
    cmp_pos: int | None = None,
    arg_pos: int | None = None,
    cmp_attr: str | None = None,
    arg_attr: str | None = None,
) -> Iterator[object]:
    """
    Applies a function to each non-None item in an iterable.

    Similar to filter(None, iterable), but excludes ``None`` instead of falsy values.
    Positional selectors are applied before attribute selectors. A ``None`` intermediate
    value remains ``None``.

    Args:

        items: The source iterable.

    Kwargs:

        func: Optional function applied to each selected value.
        cmp_pos: Item position to test for ``None``.
        arg_pos: Item position to yield (or pass to ``func``).
        cmp_attr: Attribute to test for ``None``.
        arg_attr: Attribute to yield (or pass to ``func``).

    Yields:

        Each selected non-None item, or ``func``'s result for it.
        Only the comparison value is checked for ``None``.

    Raises:

        TypeError: If a positional selector targets a non-sequence.
        AttributeError: If a selected attribute does not exist.

    Examples:

        >>> from types import SimpleNamespace
        >>>
        >>> list(gen_non_null([1, None, 0, 2]))
        [1, 0, 2]
        >>> "".join(gen_non_null(["a", None, 1], str))
        'a1'
        >>> pairs = [("a", 1), ("b", None), ("c", 0)]
        >>> list(gen_non_null(pairs, cmp_pos=1, arg_pos=0))
        ['a', 'c']
        >>> rows = [
        ...     SimpleNamespace(name="a", count=1),
        ...     SimpleNamespace(name="b", count=None)
        ... ]
        >>> list(gen_non_null(rows, cmp_attr="count", arg_attr="name"))
        ['a']

    """
    same = cmp_pos == arg_pos and cmp_attr == arg_attr
    has_cmp = cmp_pos is not None or cmp_attr is not None
    has_arg = arg_pos is not None or arg_attr is not None
    cmp_attr_only = cmp_pos is None and cmp_attr is not None
    arg_attr_only = arg_pos is None and arg_attr is not None

    pos_only = (
        cmp_pos is not None
        and arg_pos is not None
        and cmp_attr is None
        and arg_attr is None
    )

    cmp_field = cmp_attr if cmp_attr is not None else ""
    arg_field = arg_attr if arg_attr is not None else ""
    cmp_idx = cmp_pos if cmp_pos is not None else 0
    arg_idx = arg_pos if arg_pos is not None else 0
    cmp_msg = lambda item: f"Item {item!r} (via cmp_pos={cmp_pos})"
    arg_msg = lambda item: f"Item {item!r} (via arg_pos={arg_pos})"

    for item in items:
        if item is None:
            continue

        if pos_only:
            item = require_sequence(item, cmp_msg)

            if (cmp := item[cmp_idx]) is None:
                continue

            arg = cmp if same else item[arg_idx]
        else:
            if cmp_attr_only:
                cmp = getattr(item, cmp_field)
            elif has_cmp:
                cmp = _get_value(item, cmp_pos, cmp_attr, cmp_msg)
            else:
                cmp = item

            if cmp is None:
                continue

            if same:
                arg = cmp
            elif arg_attr_only:
                arg = getattr(item, arg_field)
            elif has_arg:
                arg = _get_value(item, arg_pos, arg_attr, arg_msg)
            else:
                arg = item

        yield arg if func is None else func(arg)


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

    Kwargs:

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
    predicate: Callable[[T], bool] | None, values: Iterable[T]
) -> tuple[list[T], list[T]]:
    """
    Splits an iterable into matching and non-matching lists by a predicate.

    Args:

        predicate: The test applied to each element; ``None`` tests truthiness.
        values: The source iterable.

    Returns:

        A ``(matching, non_matching)`` pair of lists, each preserving order.

    Examples:

        >>> partition(lambda n: n % 2 == 0, [1, 2, 3, 4])
        ([2, 4], [1, 3])
        >>> partition(None, [0, 1, "", "x"])
        ([1, 'x'], [0, ''])

    """
    matching: list[T] = []
    non_matching: list[T] = []
    test = bool if predicate is None else predicate

    for item in values:
        (matching if test(item) else non_matching).append(item)

    return matching, non_matching


def sort_stably[T](items: Iterable[T], key: SortKey[T] | None = None) -> tuple[T, ...]:
    """
    Sorts items in an order that does not depend on hash randomization.

    Items that cannot be compared with each other, such as a mix of types, are
    sorted by their ``repr`` instead.

    Args:

        items: The items to sort, such as a set.

    Kwargs:

        key: Optional function that produces each item's sort key. When given, items are
            sorted by it with no ``repr`` fallback.

    Returns:

        The items in a stable order.

    Examples:

        >>> sort_stably({"b", "a"})
        ('a', 'b')
        >>> sort_stably({1, "a"})
        ('a', 1)

    """
    if key is None:
        listed = list(items)

        try:
            result = sorted(listed)  # pyright: ignore[reportArgumentType]
        except TypeError:
            result = sorted(listed, key=repr)
    else:
        result = sorted(items, key=key)

    return tuple(result)


def peek[T](source: Iterable[T], n: int) -> tuple[tuple[T, ...], Iterator[T]]:
    """
    Reads up to *n* items ahead without losing them.

    Args:

        source: An iterable.
        n: The most items to read ahead.

    Returns:

        The items read ahead, and an iterator over every item of *source* in order,
            starting with them.

    Examples:

        >>> head, stream = peek(iter("abc"), 2)
        >>> head, list(stream)
        (('a', 'b'), ['a', 'b', 'c'])
        >>> peek([], 2)[0]
        ()

    """
    stream = iter(source)
    head = tuple(islice(stream, n))
    return head, chain(head, stream)


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
