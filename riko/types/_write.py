from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from riko.types._streams import AsyncItems

if TYPE_CHECKING:
    from ._io import PathLike
    from ._streams import Item, Items

type KeyLike = str | Iterable[str]


@dataclass(frozen=True, slots=True)
class WriteResult:
    """
    What a write delivery did.

    Attributes:

        created: Records inserted (keyed record targets).
        updated: Records updated (keyed record targets).
        deleted: Records removed (keyed record targets).
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


class Formats(StrEnum):
    """How a write serializes records to a destination."""

    CSV = "csv"
    GEOJSON = "geojson"
    JSON = "json"
    JSONL = "jsonl"
    OFX = "ofx"
    QIF = "qif"


type FmtLike = Formats | str
type ExportType = FmtLike | Literal["list", "tuple"]


@dataclass(frozen=True, slots=True)
class WriteCapabilities:
    """
    What a write target supports for a resolved ``(target × format)``.

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
        """Whether the target encodes records with a format, derived from ``fmt``."""
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


@dataclass(frozen=True, slots=True)
class WriteOperation:
    """
    Normalized write intent, independent of any target.

    A ``WriteOperation`` is not a fully validated write specification: whether its
    ``mode``/``keys`` are legal depends on a target's :class:`WriteCapabilities`.
    :class:`PreparedWrite` is the target-bound, validated object.

    Attributes:

        mode: How incoming records reconcile with the destination.
        keys: The keys for a keyed mode (record-match or idempotency identity,
            per the target's capabilities); empty otherwise.

    """

    mode: WriteMode
    keys: tuple[str, ...] = ()


@runtime_checkable
class WriteTarget(Protocol):
    """A destination that reports its write capabilities."""

    def capabilities(self, fmt: Formats | str | None = None) -> WriteCapabilities:
        """
        Reports the modes and serialization behavior the target supports.

        Format-dependent behavior (which modes are appendable, whether delivery is
        incremental) is a ``target × format`` fact the target itself decides; the
        returned :class:`WriteCapabilities` merely reports that decision. A native
        target ignores ``fmt``.

        Args:

            fmt: The serialization format, used by a serializing target to resolve
                its capabilities; ignored by a native target.

        Returns:

            The modes and serialization behavior the target supports.

        """
        ...


type Destination = PathLike | WriteTarget


@dataclass(frozen=True, slots=True)
class PreparedWrite:
    """
    A target-bound, validated write ready for execution.

    Attributes:

        target: The resolved write target.
        operation: The normalized, validated write intent.
        capabilities: The resolved ``(target × format)`` capabilities.

    """

    target: WriteTarget
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
    Both the passthrough ``write`` verb and the terminal ``sink`` verb consume the
    same session; terminality is a property of how the pipeline is consumed, not a
    second session type.
    """

    def write(self, value: Item | Items) -> None:  # noqa: E301
        """
        Delivers a record or the whole record stream through this session.
        """
        ...

    def acquire(self) -> None:
        """Opens the destination once for an incremental format."""
        ...

    def finalize(self) -> WriteResult:
        """
        Commits the delivery and reports what the session wrote.
        """
        ...

    def abort(self) -> None:
        """Abandons the delivery, discarding any staged, unpublished content."""
        ...

    def teardown(self) -> None:
        """Releases runtime resources; never commits."""
        ...


class AsyncWriteSession(Protocol):
    """A live, execution-owned asynchronous write session."""

    async def write(self, value: Item | Items | AsyncItems) -> None: ...  # noqa: E704
    async def aacquire(self) -> None: ...  # noqa: E704
    async def afinalize(self) -> WriteResult: ...  # noqa: E704
    def abort(self) -> None: ...  # noqa: E704
    async def ateardown(self) -> None: ...  # noqa: E704
