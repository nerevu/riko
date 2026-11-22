"""
General iterable composition, fan-out, interleaving, and deduplication helpers.

Examples:

    Basic usage::

        >>> from io import StringIO
        >>> from riko.ext import auto_close
        >>>
        >>> f = StringIO("hi")
        >>> stream = auto_close((line.upper() for line in f), f)
        >>> list(stream), f.closed
        (['HI'], True)

"""

from __future__ import annotations

import warnings
from collections import deque
from contextlib import suppress
from copy import deepcopy
from enum import StrEnum
from functools import partial
from itertools import count, cycle, dropwhile, islice, takewhile
from math import ceil, inf
from threading import Condition, Lock, get_ident
from types import GeneratorType
from typing import TYPE_CHECKING, Literal, Self, overload

import attrs

from ._config import Limit, require_limit
from ._exceptions import PipelineError, PipelineStateError
from ._guards import (
    ASYNC_CLEANUP_MSG,
    get_sync_closer,
    is_known_sequence,
    is_mapping,
    require_sequence,
    require_value,
)
from ._logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from logging import Logger

    from riko.types._frozendict import SortKey
    from riko.types._wrappers import Func

logger: Logger = get_logger(__name__)

BRANCH_LAG_MSG = (
    "a branch fell more than {} items behind its siblings; raise RIKO_BRANCH_BUFFER "
    "or read the branches together"
)
READ_INTERRUPTED_MSG = (
    "the upstream read was cancelled or interrupted by another consumer"
)


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
            item = require_sequence(item, cmp_msg, error=TypeError)

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


def fan_out[T](func: Callable[[T], T], item: T, *keys: int) -> Iterator[tuple[int, T]]:
    r"""
    Delivers the same item to a function once per key.

                /--> func(item) --> (key1, result)
               /
        item -----> func(item) --> (key2, result)
               \
                \--> func(item) --> (key3, result)

    Args:

        func: The function applied to ``item``.
        item: The value passed to ``func``.
        keys: The branches that receive it.

    Yields:

        Each key paired with its own result of ``func(item)``.

    Raises:

        PipelineError: If the function call fails.

    Examples:

        >>> from copy import copy
        >>>
        >>> dict(fan_out(copy, "a", 1, 2))
        {1: 'a', 2: 'a'}

    """
    for key in keys:
        try:
            yield key, func(item)
        except Exception as error:
            msg = "could not {} an item for branch {} of the fan-out"
            name = getattr(func, "__name__", repr(func))
            raise PipelineError(msg.format(name, key)) from error


def log_cleanup_failure(
    error: BaseException | None, failure: BaseException, msg: str
) -> None:
    """
    Logs a cleanup failure and notes it on the error it accompanies when there is one.

    Args:

        error: The error being raised, if any.
        failure: The error the cleanup raised.
        msg: What the cleanup was doing.

    Examples:

        >>> error = ValueError("read failed")
        >>> log_cleanup_failure(error, OSError("close failed"), "closing the source")
        >>> error.__notes__
        ["closing the source also failed: OSError('close failed')"]

    """
    if error is None:
        logger.warning(f"{msg} failed", exc_info=failure)
    else:
        error.add_note(f"{msg} also failed: {failure!r}")
        logger.warning(" ".join(error.__notes__), exc_info=failure)


def has_open_resource(values: Iterable[object], *ignored: type) -> bool:
    """
    Checks whether any of ``values`` is a closable resource rather than a stream.

    A value of an ``ignored`` type never counts: pass generators, which close what
    they hold when garbage collected, and wrappers, which report their own leaks. Any
    other value with ``close`` or ``aclose`` does, such as a file, a response, or a
    cursor.

    Args:

        values: The values a wrapper would close.
        ignored: The types that are not resources.

    Examples:

        >>> from io import StringIO
        >>> from types import GeneratorType
        >>>
        >>> has_open_resource([(x for x in "ab"), None], GeneratorType)
        False
        >>> has_open_resource([StringIO("hi")], GeneratorType)
        True

    """
    closables = (v for v in values if hasattr(v, "close") or hasattr(v, "aclose"))
    return not all(isinstance(v, ignored) for v in closables)


class auto_close[T]:  # noqa: N801
    """
    Passes ``source`` through so it closes ``closables`` when iteration ends.

    Closes each closable on exhaustion, an early close, or an exception. Also closes
    ``source`` if it is closable. A ``close`` before the first read releases
    everything. A value with no close (including ``None``) is skipped.

    Use ``maybe_closing`` instead when the handle is consumed inside one ``with`` block.
    This wrapper is for a handle whose consumption is deferred.

    E.g., a parser that returns a lazy iterator over an open file keeps the file alive
    until the caller drains it. A ``with`` block would close it before the first read.
    Pass a second closable when a seekable copy is read but the original fetch must
    still be released.

    Args:

        source: The items to yield.
        closables: The values closed once iteration finishes.

    Warns:

        ResourceWarning: If a wrapper holding a resource (not just generators or other
            wrappers) is read from but garbage collected before it finishes or closes.
            It closes either way, as an abandoned generator does.

    Raises:

        InvalidPipelineError: If a close returns an awaitable since there is no event
            loop.

        Exception: Whatever a failing close raises, once every closable has been
            closed.

        ExceptionGroup: If several fail. A close failure after a read error is noted
            on that error instead.

    Examples:

        >>> from io import StringIO
        >>>
        >>> f = StringIO("hi")
        >>> list(auto_close(f))
        ['hi']
        >>> f.closed
        True

        # Closing before the first read
        >>> g, h = StringIO("hi"), StringIO("extra")
        >>> auto_close(g, h).close()
        >>> g.closed, h.closed
        (True, True)

    """

    __slots__ = ("_open", "_started", "closables", "source")

    def __init__(self, source: Iterable[T], *closables: object) -> None:
        self.source: Iterator[T] = iter(source)
        self.closables: tuple[object, ...] = closables
        self._open = [True]
        self._started = False

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        self._started = True

        try:
            item = next(self.source)
        except StopIteration:
            self.close()
            raise
        except BaseException as primary:
            try:
                self.close()
            except Exception as failure:  # noqa: BLE001 (noted on the primary)
                log_cleanup_failure(primary, failure, "closing the source")

            raise

        return item

    def __del__(self) -> None:
        """Closes a started but unclosed wrapper, and warns if it holds a resource."""
        if getattr(self, "_started", False) and getattr(self, "_open", None):
            values = (getattr(self, "source", None), *getattr(self, "closables", ()))

            if has_open_resource(values, GeneratorType, auto_close):
                msg = "unclosed auto_close stream. Exhaust or close it"
                warnings.warn(msg, ResourceWarning, source=self, stacklevel=1)

            with suppress(Exception):
                self.close()

    def close(self) -> None:
        """
        Closes the source and each closable (closing again does nothing).

        Raises:

            Exception: Whatever the one failing close raises.
            ExceptionGroup: If several closes fail.

        """
        failures: list[Exception] = []

        try:
            # A single atomic pop, so concurrent callers close only once.
            self._open.pop()
        except IndexError:
            pass
        else:
            for value in (self.source, *self.closables):
                if (closer := get_sync_closer(value)) is not None:
                    try:
                        require_value(closer(), ASYNC_CLEANUP_MSG)
                    except Exception as error:  # noqa: BLE001 (raised after the loop)
                        failures.append(error)

        if len(failures) == 1:
            raise failures[0]
        elif failures:
            raise ExceptionGroup("multiple errors during auto_close", failures)


@attrs.frozen(kw_only=True)
class TeeRead[T]:
    """
    What one upstream read of a tee publishes to its branches.

    Examples:

        >>> from collections import deque
        >>>
        >>> buffers = {0: deque(), 1: deque()}
        >>> read = TeeRead.from_item([1], 0, 1, isolate=True)
        >>> read.deliver(buffers)
        >>> buffers
        {0: deque([[1]]), 1: deque([[1]])}
        >>> buffers[0][0] is buffers[1][0]
        False

    """

    values: Mapping[int, T] = attrs.field(factory=dict)
    error: Exception | None = None
    discard: bool = False
    done: bool = False

    @classmethod
    def from_lag(cls, max_lag: Limit) -> Self:
        """
        Builds the read that fails every branch once one falls too far behind.

        Args:

            max_lag: The most items a branch may have queued.

        Returns:

            A read that discards every buffer and carries the overflow error.

        """
        error = PipelineError(BRANCH_LAG_MSG.format(ceil(max_lag)))
        return cls(error=error, discard=True)

    @classmethod
    def from_interrupt(cls, exc: BaseException) -> Self:
        """
        Builds the read that fails the other branches after an interrupted read.

        Args:

            exc: What interrupted the read.

        Returns:

            A read whose error is caused by ``exc``.

        """
        error = PipelineError(READ_INTERRUPTED_MSG)
        error.__cause__ = exc
        return cls(error=error)

    @classmethod
    def from_item(cls, item: T, key: int, *others: int, isolate: bool) -> Self:
        """
        Builds the read that queues one upstream item for the reader and its siblings.

        Args:

            item: The item read.
            key: The branch that read it.
            others: The live sibling branches.

        Kwargs:

            isolate: Gives every sibling a deep copy of ``item``.

        Returns:

            A read that queues the item, or one that discards every buffer and carries
            the error when a copy fails.

        """
        if isolate:
            try:
                read = cls(values={key: item, **dict(fan_out(deepcopy, item, *others))})
            except PipelineError as copy_error:
                read = cls(error=copy_error, discard=True)
        else:
            read = cls(values=dict.fromkeys((key, *others), item))

        return read

    def deliver(self, buffers: Mapping[int, deque[T]]) -> None:
        """
        Delivers the read's values to the open branch buffers.

        Discarding clears every buffer first.

        Args:

            buffers: Each live branch's queued items.

        """
        if self.discard:
            for buffer in buffers.values():
                buffer.clear()

        for k, value in self.values.items():
            if (buffer := buffers.get(k)) is not None:
                buffer.append(value)


class _TeeState(StrEnum):
    """The lifecycle state of a tee."""

    IDLE = "idle"
    READING = "reading"
    DONE = "done"
    CLOSED = "closed"


def require_idle(state: _TeeState) -> None:
    """
    Requires an idle tee (has not started reading and hasn't closed).

    Args:

        state: The tee's state.

    Raises:

        PipelineStateError: If the tee is not idle.

    Examples:

        >>> require_idle(_TeeState.IDLE)

    """
    if state is not _TeeState.IDLE:
        raise PipelineStateError(state.value, "branch", subject="tee")


def is_lagging[T](buffers: Mapping[int, deque[T]], key: int, max_lag: Limit) -> bool:
    """
    Checks whether any of ``key``'s siblings has ``max_lag`` items queued.

    Args:

        buffers: Each live branch's queued items.
        key: The branch about to read upstream.
        max_lag: The most items a branch may have queued.

    Returns:

        Whether reading another item would overflow a sibling.

    Examples:

        >>> from collections import deque
        >>>
        >>> is_lagging({0: deque(), 1: deque([1, 2])}, 0, 2)
        True

    """
    return any(len(buffers[k]) >= max_lag for k in buffers if k != key)


class TeeBranch[T]:
    """
    One ``Tee`` branch: an iterator that releases its buffer when closed.

    Created by ``Tee.branch``. Exhausting or closing the branch drops its buffer. Once
    every branch has done so, the tee closes its source. Closing a branch while its
    consumer waits on another thread's read ends that wait at once.
    """

    __slots__ = ("_key", "_tee")

    def __init__(self, tee: Tee[T], key: int) -> None:
        self._tee = tee
        self._key = key

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        try:
            item = self._tee._pull(self._key)
        except StopIteration:
            self._tee._drop(self._key)
            raise

        return item

    def close(self) -> None:
        """Drops the branch and its buffer (closing again does nothing)."""
        self._tee._drop(self._key)


class Tee[T]:
    """
    Shares one iterator among branches pulled in any order.

    Each upstream item is pulled once, by whichever branch first asks for it. It is
    queued for every other open branch. Nothing is ever dropped. A lagging branch
    buffers, and if it falls more than ``max_lag`` items behind, fails the tee instead.
    Create every branch before reading any. Branches may be read from different threads,
    one consumer per branch.

    The source closes as soon as it is exhausted or fails, and buffered items still
    drain. An upstream error reaches every branch once it has drained what it queued.
    Every later read raises it again.

    An overflow or a failed copy discards every buffer and fails every branch at once.
    Closing the last branch while another thread is reading upstream returns at once.
    That reader closes the source when its read returns.

    Args:

        source: The items to share.

    Kwargs:

        isolate: Gives every branch but the first reader a deep copy.
        max_lag: The most items a branch may have queued (default: no bound).

    Raises:

        PipelineError: If

            - A branch would queue more than ``max_lag`` items
            - An item cannot be copied
            - Another consumer's upstream read was cancelled or interrupted.

        PipelineStateError: If a branch is created after the first read or after
            close, or the source reads a branch that has nothing queued.

        TypeError: If ``max_lag`` is neither an integer nor ``math.inf``.
        ValueError: If ``max_lag`` is 0 or negative.

    Examples:

        >>> tee = Tee([{"n": 1}, {"n": 2}], isolate=True)
        >>> first, second = tee.branch(), tee.branch()
        >>> next(first)
        {'n': 1}
        >>> list(second)
        [{'n': 1}, {'n': 2}]
        >>> list(first)
        [{'n': 2}]

    """

    __slots__ = (
        "_advancer",
        "_buffers",
        "_error",
        "_isolate",
        "_keys",
        "_lock",
        "_max_lag",
        "_ready",
        "_source",
        "_state",
    )

    def __init__(
        self, source: Iterable[T], *, isolate: bool = False, max_lag: Limit = inf
    ) -> None:
        self._max_lag = require_limit(max_lag, "max_lag")
        self._source: auto_close[T] = auto_close(source)
        self._isolate = isolate
        self._buffers: dict[int, deque[T]] = {}
        self._keys = count()
        self._lock = Lock()
        self._ready = Condition(self._lock)
        self._advancer: int | None = None
        self._state = _TeeState.IDLE
        self._error: Exception | None = None

    def _require_buffer(self, key: int) -> deque[T]:
        if (buffer := self._buffers.get(key)) is None:
            raise StopIteration

        if not buffer:
            if self._error is not None:
                raise self._error

            if self._state is _TeeState.DONE:
                raise StopIteration

            if self._advancer == get_ident():
                raise PipelineStateError("advancing", "read", subject="tee")

        return buffer

    def _publish(self, read: TeeRead[T]) -> None:
        with self._lock:
            read.deliver(self._buffers)

            if read.error is not None:
                self._error = read.error

            if read.done and self._state is _TeeState.READING:
                self._state = _TeeState.DONE

            self._advancer = None
            self._ready.notify_all()

    def _close_source(self, error: Exception | None = None) -> None:
        try:
            self._source.close()
        except BaseException as failure:
            log_cleanup_failure(error, failure, "closing the source")

            if not isinstance(failure, Exception):
                raise

    def _process(self, key: int, *, full: bool) -> TeeRead[T]:
        if full:
            read = TeeRead[T].from_lag(self._max_lag)
        else:
            try:
                item = next(self._source)
            except StopIteration:
                read = TeeRead[T](done=True)
            except Exception as read_error:  # noqa: BLE001 (latched, re-raised)
                read = TeeRead[T](error=read_error)
            else:
                # Reads keys atomically so closed branches get no copy.
                others = tuple(k for k in tuple(self._buffers) if k != key)
                read = TeeRead.from_item(item, key, *others, isolate=self._isolate)

        return read

    def _advance(self, key: int, *, full: bool) -> None:
        read = TeeRead[T]()
        interrupted: BaseException | None = None

        try:
            read = self._process(key, full=full)
        except BaseException as exc:  # noqa: BLE001 (re-raised below)
            interrupted = exc
            read = TeeRead[T].from_interrupt(exc)
        finally:
            self._publish(read)

        if read.error is not None:
            self._close_source(read.error)

        # A close requested during the read was left to this reader
        if self._state is _TeeState.CLOSED:
            self._close_source()

        if interrupted is not None:
            raise interrupted
        elif read.error is not None:
            raise read.error

    def _pull(self, key: int) -> T:
        with self._lock:
            while not (buffer := self._require_buffer(key)):
                if self._advancer is None:
                    self._advancer = get_ident()
                    self._state = _TeeState.READING
                    full = is_lagging(self._buffers, key, self._max_lag)
                    self._lock.release()

                    try:
                        self._advance(key, full=full)
                    finally:
                        self._lock.acquire()
                else:
                    self._ready.wait()

            item = buffer.popleft()

        return item

    def _drop(self, key: int) -> None:
        with self._lock:
            dropped = self._buffers.pop(key, None) is not None
            last = dropped and not self._buffers
            self._ready.notify_all()

        if last:
            self.close()

    def branch(self) -> TeeBranch[T]:
        """
        Builds a new branch that yields every item the tee reads.

        Returns:

            The branch.

        Raises:

            PipelineStateError: If the tee has started reading or has closed.

        """
        require_idle(self._state)
        key = next(self._keys)
        self._buffers[key] = deque()
        return TeeBranch(self, key)

    def close(self) -> None:
        """
        Closes the source and ends every branch.

        While another thread is reading upstream, returns at once and leaves the
        close to that reader.

        Raises:

            Exception: Whatever closing the source raises.

        """
        with self._lock:
            self._buffers.clear()
            deferred = self._advancer is not None
            self._state = _TeeState.CLOSED
            self._ready.notify_all()

        if not deferred:
            self._source.close()
