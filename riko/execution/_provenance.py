"""
Run-local item identity carried between an execution's nodes.

Each item travels between nodes inside an ``_ItemEnvelope``. A node that runs per item
applies its identity mode to each input envelope (``gen_result_envelopes``). A node that
runs over a whole stream reads and returns bare values, so ``NodeProvenance`` unwraps
its inputs and wraps its results.

A generation is a plain tuple: ``(node_id, index)`` for a root and
``(node_id, parent_generation, index)`` for a derived item. A result that keeps its
item's identity carries that item's generation unchanged. Nothing here hashes values. A
consumer that needs a durable identity should hash the generation at its own boundary
with ``digest(generation, IdentityDomain.GENERATION)``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from contextlib import suppress
from functools import cached_property
from itertools import count, repeat
from typing import TYPE_CHECKING, ClassVar, NamedTuple
from weakref import KeyedRef

from attrs import define, field

from riko.bado._util import maybe_aclosing, maybe_closing
from riko.bado.itertools import alist, amap, apeek, as_async
from riko.base._config import FOREVER_ITEM
from riko.base._iterutils import peek
from riko.base._sentinels import MISSING, MissingType, is_missing_type
from riko.coercion._canonical import IdentityAccumulator, IdentityDomain
from riko.types._enums import IdentityMode
from riko.types._feed import (
    AsyncEnvelopeGenerator,
    AsyncEnvelopeStream,
    EnvelopeGenerator,
    EnvelopeList,
    Envelopes,
    EnvelopeStream,
    _ItemEnvelope,
    build_generation,
)
from riko.types._frozendict import FrozenDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Sequence

    from riko.types._feed import (
        AnyEnvelopes,
        AsyncItemCall,
        Generation,
        Identity,
        ItemCall,
        Metadata,
    )
    from riko.types._streams import AnyIterable
    from riko.types._workflow import NodeId
    from riko.types._wrappers import Func

# The seed item that starts a source. Its item_key and generation stay MISSING.
PLACEHOLDER: _ItemEnvelope[object] = _ItemEnvelope(FrozenDict(FOREVER_ITEM))


class _Entry[T](NamedTuple):
    key: Identity
    generation: Generation | MissingType
    observation: Metadata | None
    ref: KeyedRef[int, T]


def _map_results[T](
    node_id: NodeId,
    parent: _ItemEnvelope[object],
    preserves: bool,
    results: Iterable[T],
) -> EnvelopeStream[T]:
    if preserves:
        envelopes = map(parent.with_value, results)
    else:
        args = (repeat(parent), repeat(node_id), results, count())
        envelopes = map(_ItemEnvelope.from_parent, *args)

    return envelopes


def _reads_head(parent: _ItemEnvelope[object], identity: IdentityMode | None) -> bool:
    return identity is None and not is_missing_type(parent.generation)


def _resolve_preserves(
    parent: _ItemEnvelope[object], identity: IdentityMode | None, head: Sequence[object]
) -> bool:
    """
    Resolves whether a node's per-item results keep the input item's identity.

    A placeholder parent never passes its identity on, so its results are roots. A node
    that declares no mode preserves only when the item produced exactly one result.

    Args:

        parent: The input item's envelope.
        identity: The node's identity mode.
        head: The item's first two results (all of them when it has fewer).

    Returns:

        ``True`` when every result keeps ``parent``'s identity.

    """
    if is_missing_type(parent.generation):
        preserves = False
    elif identity is None:
        preserves = len(head) == 1
    else:
        preserves = identity is IdentityMode.PRESERVE

    return preserves


def gen_result_envelopes[T](
    node_id: NodeId,
    results: Iterable[T],
    parent: _ItemEnvelope[object] = PLACEHOLDER,
    identity: IdentityMode | None = None,
) -> EnvelopeStream[T]:
    """
    Wraps each of a node's per-item results in an envelope.

    Args:

        node_id: Id of the node that produced the results.
        results: The node's per-item results for one input item.

    Kwargs:

        parent: The input item's envelope. Results read from the placeholder item are
            roots, which never read ahead.

        identity: The node's identity mode.

            - ``PRESERVE`` keeps the input item's identity on each result.

            - ``DERIVE`` and ``COMBINE`` give each result a new identity built from
              the input item's identity and the result's position.

            - ``None`` keeps the identity when the item produced exactly one result and
              derives one per result otherwise.

            Telling those apart reads at most two results ahead, so the results stay
            lazy.

    Yields:

        One envelope per result.

    Examples:

        >>> parent = _ItemEnvelope("a b", generation=("fetch", 0))
        >>> identity = IdentityMode.PRESERVE
        >>> kept = gen_result_envelopes("upper", ["A B"], parent, identity)
        >>> next(kept).generation == parent.generation
        True
        >>> split = list(gen_result_envelopes("split", ["a", "b"], parent))
        >>> [envelope.value for envelope in split]
        ['a', 'b']
        >>> split[0].generation == parent.generation
        False

    """
    head, stream = peek(results, 2 if _reads_head(parent, identity) else 0)
    preserves = _resolve_preserves(parent, identity, head)
    yield from _map_results(node_id, parent, preserves, stream)


async def agen_result_envelopes[T](
    node_id: NodeId,
    results: AnyIterable[T],
    parent: _ItemEnvelope[object] = PLACEHOLDER,
    identity: IdentityMode | None = None,
) -> AsyncEnvelopeStream[T]:
    """
    Wraps each of a node's per-item results in an envelope.

    Applies the same rule as ``gen_result_envelopes`` to a sync or async iterable.

    Args:

        node_id: Id of the node that produced the results.
        results: The node's per-item results for one input item.

    Kwargs:

        parent: The input item's envelope; the placeholder item makes roots.

        identity: The node's identity mode.

            - ``PRESERVE`` keeps the input item's identity on each result.

            - ``DERIVE`` and ``COMBINE`` give each result a new identity built from
              the input item's identity and the result's position.

            - ``None`` keeps the identity when the item produced exactly one result and
              derives one per result otherwise.

            Telling those apart reads at most two results ahead, so the results stay
            lazy.

    Yields:

        One envelope per result.

    Examples:

        >>> from riko import alist, run
        >>>
        >>> parent = _ItemEnvelope("a", generation=("fetch", 0))
        >>> identity = IdentityMode.PRESERVE
        >>> envelopes = agen_result_envelopes("upper", ["A"], parent, identity)
        >>> [envelope.value for envelope in run(alist, envelopes)]
        ['A']

    """
    head, stream = await apeek(results, 2 if _reads_head(parent, identity) else 0)
    preserves = _resolve_preserves(parent, identity, head)
    index = 0

    async for result in stream:
        if preserves:
            yield parent.with_value(result)
        else:
            yield _ItemEnvelope.from_parent(parent, node_id, result, index)

        index += 1


def run_tracked_item[T](
    call: ItemCall[T],
    node_id: NodeId,
    identity: IdentityMode | None,
    envelope: _ItemEnvelope[T],
) -> EnvelopeList[T]:
    """
    Runs a per-item call on an envelope's value and wraps each result in a new envelope.

    Defined at module level so that ``partial(run_tracked_item, …)`` is picklable.

    Args:

        call: The node's per-item call.
        node_id: Id of the node the call belongs to.
        identity: The node's identity mode.
        envelope: The input item's envelope.

    Returns:

        The results' envelopes.

    Examples:

        >>> parent = _ItemEnvelope(2, generation=("fetch", 0))
        >>> call = lambda x: iter((x, x))
        >>> envelopes = run_tracked_item(call, "double", None, parent)
        >>> [envelope.value for envelope in envelopes]
        [2, 2]

    """
    # collected into a list so they cross the pool boundary in one piece
    return list(gen_result_envelopes(node_id, call(envelope.value), envelope, identity))


async def arun_tracked_item[T](
    call: AsyncItemCall[T],
    node_id: NodeId,
    identity: IdentityMode | None,
    envelope: _ItemEnvelope[T],
) -> EnvelopeList[T]:
    """
    Runs an async per-item call on an envelope's value and wraps each result.

    The async twin of ``run_tracked_item``. The call's results are closed either once
    collected or when collection fails.

    Args:

        call: The node's async per-item call.
        node_id: Id of the node the call belongs to.
        identity: The node's identity mode.
        envelope: The input item's envelope.

    Returns:

        The results' envelopes.

    Examples:

        >>> from riko import as_async, run
        >>>
        >>> parent = _ItemEnvelope(2, generation=("fetch", 0))
        >>> args = (lambda x: as_async((x, x)), "double", None, parent)
        >>> [envelope.value for envelope in run(arun_tracked_item, *args)]
        [2, 2]

    """
    async with maybe_aclosing(call(envelope.value)) as results:
        stream = agen_result_envelopes(node_id, results, envelope, identity)
        envelopes = await alist(stream)

    return envelopes


def _build_contributors() -> IdentityAccumulator:
    return IdentityAccumulator(IdentityDomain.GENERATION)


@define(eq=False)
class NodeProvenance[T](ABC):
    """
    Tracks item identity through a node that runs over a whole stream.

    The node reads and returns bare values, so its inputs are unwrapped and tracked on
    the way in, and its results are wrapped on the way out:

    - A result that is an input passed through unchanged, e.g., a ``filter`` item,
      keeps that input's envelope.
    - When the same input arrives more than once, e.g., an item an earlier node
      emitted twice, its pass-through results get its envelopes back in arrival order.
    - Any other result derives from the last input read and its position.
    - Under ``COMBINE``, every result derives from all of the node's inputs.

    An input that can't be tracked, e.g., a ``dict`` or string, gets a new identity
    unless the node converts it into one that can, e.g., a ``DotDict``. Each instance
    serves one node stream of one execution.

    Args:

        node_id: Id of the node whose items this tracks.

    Examples:

        >>> from riko.parsing._dotdict import DotDict
        >>>
        >>> envelope = _ItemEnvelope(DotDict({"x": 1}), generation=("fetch", 0))
        >>> provenance = NodeProvenance.from_identity("filter", IdentityMode.PRESERVE)
        >>> values = provenance.gen_values([envelope])
        >>> kept = next(provenance.gen_envelopes(values))
        >>> kept.generation == envelope.generation
        True

    """

    node_id: NodeId
    _tracks_values: ClassVar[bool] = True

    @classmethod
    def from_identity(
        cls, node_id: NodeId, identity: IdentityMode | None
    ) -> NodeProvenance[T]:
        """
        Builds the provenance that applies a node's identity mode.

        Args:

            node_id: Id of the node whose items this tracks.
            identity: The node's identity mode.

        Returns:

            Provenance that derives every result from all of the node's inputs
            (``COMBINE``), or else tracks each input so a result that passes it
            through keeps its envelope.

        Examples:

            >>> provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            >>> provenance.node_id
            'count'

        """
        provenance: NodeProvenance[T]

        if identity is IdentityMode.COMBINE:
            provenance = _FoldProvenance(node_id)
        else:
            provenance = _TableProvenance(node_id)

        return provenance

    @abstractmethod
    def _unwrap(self, envelope: _ItemEnvelope[object]) -> object:
        """Reads one input envelope and returns the value the node sees."""

    @abstractmethod
    def _wrap(self, value: T, index: int) -> _ItemEnvelope[T]:
        """Wraps the node's result at ``index`` in an envelope."""

    def _release(self) -> None:  # noqa: B027
        """Drops whatever the inputs left behind once the results are wrapped."""

    def _resolve_unwrap(
        self, item_normalizer: Func[object] | None
    ) -> Callable[[_ItemEnvelope[T]], object]:

        def unwrap(envelope: _ItemEnvelope[T]) -> object:
            if item_normalizer is None or not self._tracks_values:
                _envelope = envelope
            else:
                _envelope = envelope.with_value(item_normalizer(envelope.value))

            return self._unwrap(_envelope)

        return unwrap

    def gen_values(
        self, envelopes: Envelopes[T], item_normalizer: Func[object] | None = None
    ) -> Iterator[object]:
        """
        Unwraps each input envelope and tracks which envelope each value came from.

        Tracking lets a value the node passes through unchanged, e.g., a ``filter``
        item, keep its envelope. For a value that can't be tracked, e.g., a ``dict`` or
        string, ``item_normalizer`` converts it into one that can, e.g., a ``DotDict``.

        Under ``COMBINE``, values are yielded as they are.

        Args:

            envelopes: The node's input envelopes.

        Kwargs:

            item_normalizer: Converts each value into a type that can be tracked.
                ``None`` yields values unchanged.

        Yields:

            Each input value.

        Examples:

            >>> provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            >>> list(provenance.gen_values([_ItemEnvelope(1, generation=("a", 0))]))
            [1]

        """
        yield from map(self._resolve_unwrap(item_normalizer), envelopes)

    def agen_values(
        self, envelopes: AnyEnvelopes[T], item_normalizer: Func[object] | None = None
    ) -> AsyncIterator[object]:
        """
        Unwraps each async input envelope and tracks each value's source envelope.

        Tracking lets a value the node passes through unchanged, e.g., a ``filter``
        item, keep its envelope. For a value that can't be tracked, e.g., a ``dict`` or
        string, ``item_normalizer`` converts it into one that can, e.g., a ``DotDict``.

        Under ``COMBINE``, values are returned as they are.

        Args:

            envelopes: The node's sync or async input envelopes.

        Kwargs:

            item_normalizer: Converts each value into a type that can be tracked.
                ``None`` yields values unchanged.

        Returns:

            Each input value.

        Examples:

            >>> from riko import alist, run
            >>>
            >>> provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            >>> envelopes = [_ItemEnvelope(1, generation=("a", 0))]
            >>> run(alist, provenance.agen_values(envelopes))
            [1]

        """
        return amap(self._resolve_unwrap(item_normalizer), as_async(envelopes))

    def gen_envelopes(self, results: Iterable[T]) -> EnvelopeGenerator[T]:
        """
        Wraps a sync node's results in envelopes.

        A result passed through a node that doesn't change its input's value, e.g.,
        ``filter``, keeps its envelope. A result passed through a node that creates a
        new object, e.g., a ``count``, receives a new identity. Exhausting, closing, or
        failing the generator closes ``results`` and drops the remaining input.

        Args:

            results: The node's results.

        Yields:

            One envelope per result.

        Examples:

            >>> provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            >>> total = next(provenance.gen_envelopes([3]))
            >>> total.value, total.generation[0], len(total.generation[1])
            (3, 'count', 32)

        """
        try:
            with maybe_closing(iter(results)) as stream:
                yield from map(self._wrap, stream, count())
        finally:
            self._release()

    async def agen_envelopes(
        self, results: AnyIterable[T]
    ) -> AsyncEnvelopeGenerator[T]:
        """
        Wraps an async node's results in envelopes.

        A result passed through a node that doesn't change its input's value, e.g.,
        ``filter``, keeps its envelope. A result passed through a node that creates a
        new object, e.g., a ``count``, receives a new identity. Exhausting, closing, or
        failing the generator closes ``results`` and drops the remaining input.

        Args:

            results: The node's results, sync or async.

        Yields:

            One envelope per result.

        Examples:

            >>> from riko import run
            >>>
            >>> provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            >>> run(anext, provenance.agen_envelopes([3])).value
            3

        """
        wrap = self._wrap
        index = 0

        try:
            async with maybe_aclosing(as_async(results)) as stream:
                async for result in stream:
                    yield wrap(result, index)
                    index += 1
        finally:
            self._release()


@define(eq=False)
class _TableProvenance[T](NodeProvenance[T]):
    """Tracks each input's envelope for the results that pass that input through."""

    _table: dict[int, _Entry[object]] = field(init=False, factory=dict)
    _repeats: dict[int, deque[_Entry[object]]] = field(init=False, factory=dict)
    _last: Generation | MissingType = field(init=False, default=MISSING)

    def _drop(self, ref: KeyedRef[int, object]) -> None:
        entry = self._table.get(ref.key)

        if entry is not None and entry.ref is ref:
            del self._table[ref.key]
            self._repeats.pop(ref.key, None)

    @cached_property
    def _forget(self) -> Callable[[KeyedRef[int, object]], None]:
        return self._drop

    def _unwrap(self, envelope: _ItemEnvelope[object]) -> object:
        value, generation = envelope.value, envelope.generation
        self._last = generation
        key = id(value)
        entry = self._table.get(key)
        args = (envelope.item_key, generation, envelope.observation)

        if entry is not None and entry.ref() is value:
            repeat = _Entry(*args, entry.ref)
            self._repeats.setdefault(key, deque()).append(repeat)
        else:
            with suppress(TypeError):
                ref = KeyedRef(value, self._forget, key)
                self._table[key] = _Entry(*args, ref)

        return value

    def _wrap(self, value: T, index: int) -> _ItemEnvelope[T]:
        key = id(value)
        entry = self._table.pop(key, None)

        if entry is not None and entry.ref() is value:
            if self._repeats and (repeats := self._repeats.get(key)):
                self._table[key] = repeats.popleft()

            args = (value, entry.key, entry.generation, entry.observation)
            result = _ItemEnvelope(*args)
        else:
            generation = build_generation(self.node_id, self._last, index)
            result = _ItemEnvelope(value, generation=generation)

        return result

    def _release(self) -> None:
        self._table.clear()
        self._repeats.clear()


@define(eq=False)
class _FoldProvenance[T](NodeProvenance[T]):
    """Derives every result from all of the node's inputs."""

    _contributors: IdentityAccumulator = field(init=False, factory=_build_contributors)
    _tracks_values: ClassVar[bool] = False

    def _unwrap(self, envelope: _ItemEnvelope[object]) -> object:
        generation = envelope.generation
        self._contributors.add(None if is_missing_type(generation) else generation)
        return envelope.value

    def _wrap(self, value: T, index: int) -> _ItemEnvelope[T]:
        accumulated = self._contributors.digest()
        return _ItemEnvelope(value, generation=(self.node_id, accumulated, index))
