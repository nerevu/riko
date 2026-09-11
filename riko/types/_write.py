from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ._io import PathLike
    from ._streams import Item

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


class WriteSession(Protocol):
    """
    A live, execution-owned write session.

    The specification (``Target`` × ``Format`` × ``WriteOperation``) says *what* to
    write; a ``WriteSession`` performs *how this execution* writes it — an
    execution-scoped lifecycle of acquire, write item, finalize, and teardown. A
    session is never constructed by the caller: it is the value yielded by the
    :func:`write_session` lifecycle that :meth:`riko.resources.Resource.from_lifecycle`
    wraps, so the execution layer drives entry and teardown.

    Both the passthrough ``write`` verb and the terminal ``sink`` verb consume the same
    session; terminality is a property of how the pipeline is consumed, not a second
    session type.
    """

    def write(self, item: Item) -> None:
        """
        Delivers one record through this session.

        Args:

            item: The record to deliver, written incrementally or buffered per the
                negotiated strategy.

        """
        ...

    async def awrite(self, item: Item) -> None:
        """
        Asynchronously delivers one record through this session.

        Args:

            item: The record to deliver.

        """
        ...

    def finalize(self) -> WriteResult:
        """
        Finalizes the session, flushing any buffered document.

        Returns:

            The aggregated result describing what the session wrote.

        """
        ...

    def teardown(self) -> None:
        """
        Tears down the session, flushing any buffered document and releasing resources.

        The session is no longer usable after teardown.

        """
        ...

    def abort(self) -> None:
        """
        Aborts the session, discarding any buffered document.

        The session is no longer usable after aborting.

        """
        ...


class WriteMode(StrEnum):
    """How a write reconciles incoming items with the destination."""

    APPEND = "append"
    MERGE = "merge"
    REPLACE = "replace"
    DELETE = "delete"

    @property
    def destructive(self) -> bool:
        """Whether the mode removes or overwrites records (plan/apply gated)."""
        return self in _DESTRUCTIVE


_DESTRUCTIVE = frozenset({WriteMode.REPLACE, WriteMode.DELETE})


class Formats(StrEnum):
    """How a write serializes records to a destination."""

    CSV = "csv"
    GEOJSON = "geojson"
    JSON = "json"
    JSONL = "jsonl"
    OFX = "ofx"
    QIF = "qif"


type FmtLike = Formats | str
STREAMABLE_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})
APPENDABLE_FORMATS: frozenset[Formats] = frozenset({Formats.CSV, Formats.JSONL})
type ExportType = FmtLike | Literal["list", "tuple"]


@dataclass(frozen=True, slots=True)
class WriteCapabilities:
    """
    What a write target supports.

    Attributes:

        modes: The ``WriteMode`` values the target accepts.

        serializes: Whether the target encodes records with a format (a file),
            as opposed to sending native records (a record store).

        keyed: The ``WriteMode`` values that require a match key for the target.

    """

    modes: frozenset[WriteMode]
    fmt: Formats
    serializes: bool = False
    streamable: bool = False
    appendable: bool = False
    match_keyed_modes: frozenset[WriteMode] = frozenset()
    idempotent_modes: frozenset[WriteMode] = frozenset()

    @property
    def keyed_modes(self) -> frozenset[WriteMode]:
        return self.match_keyed_modes | self.idempotent_modes

    def __post_init__(self):
        fmt = self.fmt
        modes = self.modes

        if difference := self.keyed_modes - self.modes:
            msg = f"keyed_modes {difference} not present in {modes=}"
        elif overlap := self.match_keyed_modes & self.idempotent_modes:
            msg = f"match_keyed_modes and idempotent_modes must not overlap; {overlap=}"
        elif WriteMode.APPEND in self.modes and not self.appendable:
            msg = f"{fmt=} does not support append."
        else:
            msg = ""

        if msg:
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class WriteOperation:
    """
    A normalized, validated write specification.

    Attributes:

        mode: How incoming records reconcile with the destination.
        keys: The match keys for a keyed mode; empty otherwise.

    """

    mode: WriteMode
    keys: tuple[str, ...] = ()


@runtime_checkable
class WriteTarget(Protocol):
    """
    A destination that reports its capabilities and delivers records.
    """

    def capabilities(self, fmt: Formats | str | None = None) -> WriteCapabilities:
        """
        Reports the modes and serialization behavior the target supports.

        For a serializing target the supported modes depend on ``fmt``: only a
        line-oriented format (csv/jsonl) can be appended to; a whole-document
        format (json/geojson/…) supports ``replace`` only. Non-serializing
        targets ignore ``fmt``.

        Args:

            fmt: The serialization format, used to decide which modes a
                serializing target allows; ignored by non-serializing targets.

        Returns:

            The modes and serialization behavior the target supports.

        """
        ...


type Destination = PathLike | WriteTarget


@dataclass(frozen=True, slots=True)
class PreparedWrite:
    target: WriteTarget
    operation: WriteOperation
    capabilities: WriteCapabilities

    @property
    def fmt(self) -> Formats:
        return self.capabilities.fmt
