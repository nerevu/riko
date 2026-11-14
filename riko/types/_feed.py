"""
Feed results, result metadata, and the item's identity envelope.

A ``FeedResult`` pairs a stream of items with the facts that describe the stream
(``Metadata``) and an optional resumable ``FeedState``. ``_ItemEnvelope`` is the
execution-owned envelope that keeps an item's identity beside its value while the item
moves between nodes. Modules never see it.
"""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Iterator,
)
from typing import TYPE_CHECKING, NamedTuple

from attrs import define

from riko.base._sentinels import MISSING, MissingType, is_missing_type

from ._frozendict import FrozenDict

if TYPE_CHECKING:
    from ._scalars import Hashable
    from ._streams import AnyIterable
    from ._workflow import NodeId

type Generation = tuple[NodeId, int] | tuple[NodeId, Generation | str, int]
type Identity = Hashable | MissingType

type SyncFeedResult[T] = FeedResult[Iterable[T]]
type Envelopes[T] = Iterable[_ItemEnvelope[T]]
type EnvelopeStream[T] = Iterator[_ItemEnvelope[T]]
type EnvelopeGenerator[T] = Generator[_ItemEnvelope[T], None]
type EnvelopeList[T] = list[_ItemEnvelope[T]]
type TrackedCall[T] = Callable[[_ItemEnvelope[T]], EnvelopeList[T]]
type ItemCall[T] = Callable[[T], Iterator[T]]

type AsyncFeedResult[T] = FeedResult[AsyncIterable[T]]
type AsyncEnvelopes[T] = AsyncIterable[_ItemEnvelope[T]]
type AsyncEnvelopeStream[T] = AsyncIterator[_ItemEnvelope[T]]
type AsyncEnvelopeGenerator[T] = AsyncGenerator[_ItemEnvelope[T], None]
type AsyncTrackedCall[T] = Callable[[_ItemEnvelope[T]], Awaitable[EnvelopeList[T]]]
type AsyncItemCall[T] = Callable[[T], AsyncIterator[T]]

type AnyEnvelopes[T] = AnyIterable[_ItemEnvelope[T]]


class Metadata(FrozenDict[str, object]):
    """
    Facts about a stream as a whole, not about any one item.

    Read it by key or by attribute. Key access is authoritative and reaches every key.
    Attribute access is a convenience for keys that do not collide with a mapping method
    or attribute. E.g., ``metadata.keys`` is always the method, never a ``"keys"``
    entry. Like other mappings, contents decide equality and canonical identity.

    Args:

        data: The facts, as a mapping or key/value pairs.

    Examples:

        >>> metadata = Metadata({"title": "News", "keys": 2})
        >>> metadata.title
        'News'
        >>> metadata["keys"], callable(metadata.keys)
        (2, True)
        >>> metadata == {"title": "News", "keys": 2}
        True

    """

    __slots__ = ()

    def __getattr__(self, name: str) -> object:
        # copy/pickle probe attributes before ``_data`` is set
        if name == "_data" or name not in self._data:
            raise AttributeError(name)

        return self._data[name]

    def __repr__(self) -> str:
        return f"Metadata({dict(self._data)!r})"


EMPTY_METADATA: Metadata = Metadata()


@define(frozen=True, slots=True)
class FeedState[T]:
    """
    The resumable state a feed reports beside its result.

    Args:

        checkpoint: Where a later read resumes (``MISSING`` when the feed has none).
        observation: Facts observed while reading (``None`` when nothing was observed).

    Examples:

        >>> state = FeedState("2026-01-01", Metadata({"etag": "abc"}))
        >>> state.checkpoint, state.observation.etag
        ('2026-01-01', 'abc')
        >>> FeedState().checkpoint
        <MISSING>

    """

    checkpoint: T | MissingType = MISSING
    observation: Metadata | None = None


@define(frozen=True, slots=True)
class FeedResult[Items]:
    """
    A stream of items plus the facts that describe them.

    Args:

        items: A sync or async iterable.
        metadata: Result-scope facts (default: empty).
        state: The feed's resumable state (``None`` when it reports none).

    Examples:

        >>> result = FeedResult([{"x": 1}], Metadata({"title": "News"}))
        >>> list(result.items), result.metadata.title, result.state
        ([{'x': 1}], 'News', None)

    """

    items: Items
    metadata: Metadata = EMPTY_METADATA
    state: FeedState[object] | None = None


def build_generation(
    node_id: NodeId, parent: Generation | MissingType, index: int
) -> Generation:
    """
    Builds an item's generation, its run-local identity.

    The identity is a combination of the node's id, the parent's identity, and the
    item's position among the node's per-item results for its parent. The same run
    over the same input always rebuilds the same identity. A ``MISSING`` parent makes
    the item a root, i.e., ``(node_id, index)``. The result is a readable value (not a
    hash). Code that needs a hash, e.g., a checkpoint, should pass the result to
    ``digest``.

    Args:

        node_id: Id of the node that produces the item.
        parent: The identity the item descends from, or ``MISSING`` for a root.
        index: The item's position among the node's per-item results for ``parent``.

    Returns:

        The item identity.

    Examples:

        >>> root = build_generation("fetch", MISSING, 0)
        >>> root
        ('fetch', 0)
        >>> build_generation("tokenizer", root, 1)
        ('tokenizer', ('fetch', 0), 1)

    """
    if is_missing_type(parent):
        generation: Generation = (node_id, index)
    else:
        generation = (node_id, parent, index)

    return generation


class _ItemEnvelope[T](NamedTuple):
    """
    An item plus the identity an execution needs to track it between nodes.

    An immutable record. Read it by field name. It compares equal to a plain tuple of
    the same fields, so never mix envelopes with bare tuples. It pickles, so it can
    cross a process pool.

    Args:

        value: The item a module receives and yields.
        item_key: The item's durable key, or ``MISSING``.

        generation: The item's run-local identity, or ``MISSING``. It names this
            occurrence of the item within one run: ``(node_id, index)`` for a root and
            ``(node_id, parent, index)`` for a derived item. ``parent`` is the
            generation it descends from, or the digest of the generations a combined
            item folds.

        observation: Facts observed for this item, or ``None``.

    Examples:

        >>> envelope = _ItemEnvelope({"x": 1}, generation=("fetch", 0))
        >>> moved = envelope.with_value({"x": 2})
        >>> moved.value
        {'x': 2}
        >>> moved.generation
        ('fetch', 0)

    """

    value: T
    item_key: Identity = MISSING
    generation: Generation | MissingType = MISSING
    observation: Metadata | None = None

    @classmethod
    def from_parent[R](
        cls, parent: _ItemEnvelope[object], node_id: NodeId, value: R, index: int = 0
    ) -> _ItemEnvelope[R]:
        """
        Builds the envelope of a new item derived from ``parent``.

        The new item inherits its parent's observation and gets a new generation.

        Args:

            parent: The envelope the new item derives from.
            node_id: Id of the node that yields the new item.
            value: The new item.

        Kwargs:

            index: The new item's position among the node's per-item results for
                ``parent`` (default: 0).

        Returns:

            The new item's envelope.

        Examples:

            >>> parent = _ItemEnvelope("a b", generation=("fetch", 0))
            >>> child = _ItemEnvelope.from_parent(parent, "split", "b", 1)
            >>> child.generation
            ('split', ('fetch', 0), 1)

        """
        generation = build_generation(node_id, parent.generation, index)
        return _ItemEnvelope(value, MISSING, generation, parent.observation)

    def with_value[R](self, value: R) -> _ItemEnvelope[R]:
        """
        Builds an envelope for a new value that preserves this item's identity.

        Args:

            value: The value the new envelope carries.

        Returns:

            A copy of this envelope with ``value`` in place of its value.

        Examples:

            >>> _ItemEnvelope(1, "k", ("n", 0)).with_value(2)
            _ItemEnvelope(value=2, item_key='k', generation=('n', 0), observation=None)

        """
        return _ItemEnvelope(value, self.item_key, self.generation, self.observation)
