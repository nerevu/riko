"""Declarative write modes, capabilities, results, and session contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol

from attrs import define, field

from riko.base._require_guards import normalize_strs
from riko.base._typing import resolve_enum
from riko.types._enums import FmtLike, Formats
from riko.types._io import PathLike
from riko.types._target_protocols import SupportsWrite

if TYPE_CHECKING:
    from riko.types._streams import Feed, Item, Items

type ExportType = FmtLike | Literal["list", "tuple"]

_keys_converter = partial(
    normalize_strs,
    what="WriteOperation 'keys'",
    type_error=TypeError,
    value_error=ValueError,
)


@dataclass(frozen=True, slots=True)
class WriteResult:
    """
    What a write delivery did.

    Attributes:

        created: Items inserted (keyed record targets).
        updated: Items updated (keyed record targets).
        deleted: Items removed (keyed record targets).
        written: Bytes written (serializing file targets).

    """

    created: int = 0
    updated: int = 0
    deleted: int = 0
    written: int = 0


class WriteMode(StrEnum):
    """How a write reconciles incoming items with the destination."""

    APPEND = "append"
    MERGE = "merge"
    REPLACE = "replace"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class WriteCapabilities:
    """
    What a ``SupportsWrite`` target supports for a resolved ``(target × format)``.

    ``incremental`` says the target can make delivery progress before the whole
    logical input is known (a line-oriented file), rather than needing the complete
    document first (a framed file). ``appendable`` and ``serializes`` are derived
    facts, not stored state: appendability is exactly ``APPEND in modes``, and a
    target serializes exactly when it resolved a format.

    Attributes:

        modes: The ``WriteMode`` values the target accepts.
        fmt: The resolved serialization format, or ``None`` for a native target.
        incremental: Whether delivery can progress before the input is complete.
        match_keyed_modes: Modes whose keys identify records to reconcile against.
        idempotent_modes: Modes whose keys deduplicate an otherwise-additive write.

    """

    modes: frozenset[WriteMode]
    fmt: Formats | None = None
    incremental: bool = False
    match_keyed_modes: frozenset[WriteMode] = frozenset()
    idempotent_modes: frozenset[WriteMode] = frozenset()

    @property
    def keyed_modes(self) -> frozenset[WriteMode]:
        """The union of the match-keyed and idempotent mode sets."""
        return self.match_keyed_modes | self.idempotent_modes

    @property
    def appendable(self) -> bool:
        """Whether the target accepts ``append``, derived from ``modes``."""
        return WriteMode.APPEND in self.modes

    @property
    def serializes(self) -> bool:
        """Whether the target encodes items with a format, derived from ``fmt``."""
        return self.fmt is not None

    def __post_init__(self) -> None:
        if difference := self.keyed_modes - self.modes:
            msg = f"keyed modes {difference!r} are not present in modes"
        elif overlap := self.match_keyed_modes & self.idempotent_modes:
            msg = f"match_keyed_modes and idempotent_modes must not overlap; {overlap=}"
        else:
            msg = ""

        if msg:
            raise ValueError(msg)


@define(frozen=True, slots=True)
class WriteOperation:
    """
    Normalized write intent, independent of any target.

    A ``WriteOperation`` is not a fully validated write specification: whether its
    ``mode``/``keys`` are legal depends on a target's :class:`WriteCapabilities`.
    :class:`PreparedWrite` is the validated write that has been checked against its
    target's capabilities.

    Attributes:

        mode: How incoming items reconcile with the destination.
        keys: The keys for a keyed mode (record-match or idempotency identity,
            per the target's capabilities); empty otherwise.

    """

    mode: WriteMode = field(
        converter=partial(resolve_enum, WriteMode, error=ValueError)
    )
    keys: tuple[str, ...] = field(factory=tuple, converter=_keys_converter)


type Destination = PathLike | SupportsWrite


@dataclass(frozen=True, slots=True)
class PreparedWrite:
    """
    A validated, target-capability-checked, ready-to-execute write.

    Attributes:

        target: The resolved ``SupportsWrite`` target.
        operation: The normalized, validated write intent.
        capabilities: The resolved ``(target × format)`` capabilities.

    """

    target: SupportsWrite
    operation: WriteOperation
    capabilities: WriteCapabilities

    @property
    def fmt(self) -> Formats | None:
        """The resolved serialization format, or ``None`` for a native target."""
        return self.capabilities.fmt


class SyncWriteSession(Protocol):
    """
    A live, execution-owned synchronous write session.

    A :class:`PreparedWrite` says *what* to write; a session performs *how this
    execution* writes it, as three distinct operations plus resource teardown:

    * ``finalize`` commits successful logical delivery.
    * ``abort`` abandons the logical delivery.
    * ``teardown`` releases runtime resources and never commits.

    A session is never constructed by the caller: the execution host acquires it,
    drives ``write``, then chooses ``finalize`` or ``abort`` before ``teardown``.
    One session type serves every write, whatever consumes the pipeline.
    """

    def write(self, value: Item | Items) -> None:
        """Delivers an item or the whole stream through this session."""
        ...

    def acquire(self) -> None:
        """Opens the destination once for an incremental format."""
        ...

    def finalize(self) -> WriteResult:
        """Commits the delivery and reports what the session wrote."""
        ...

    def abort(self) -> None:
        """Abandons the delivery, discarding any staged, unpublished content."""
        ...

    def teardown(self) -> None:
        """Releases runtime resources; never commits."""
        ...


class AsyncWriteSession(Protocol):
    """A live, execution-owned asynchronous write session."""

    async def awrite(self, value: Item | Feed) -> None: ...
    async def aacquire(self) -> None: ...
    async def afinalize(self) -> WriteResult: ...
    def abort(self) -> None: ...
    async def ateardown(self) -> None: ...
