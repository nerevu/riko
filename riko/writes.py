# vim: sw=4:ts=4:expandtab
"""
riko.writes
~~~~~~~~~~~

Write-mode contract (PRIVATE).

Defines how a write reconciles incoming items with a destination:
``append`` (add rows, deduplicated by an optional ``idempotency_key``), ``merge``
(upsert on match ``keys``), and the destructive ``replace``/``delete`` (match on
``keys``, gated behind plan/apply). This is the shared vocabulary external
provider targets (Airtable, ...) consume so every write behaves consistently; the
transports themselves live outside core. It is a distinct axis from the file-open
``mode`` used by the ``write`` module.

Examples:

    Basic usage::

        >>> from riko.writes import WriteMode, write_operation
        >>>
        >>> write_operation("merge", keys="endpoint_id")
        WriteOperation(mode=<WriteMode.MERGE: 'merge'>, keys=('endpoint_id',), idempotency_key=())
        >>> WriteMode.DELETE.destructive
        True

"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

type KeyLike = str | Iterable[str]


class WriteMode(StrEnum):
    """How a write reconciles incoming items with the destination."""

    APPEND = "append"
    MERGE = "merge"
    REPLACE = "replace"
    DELETE = "delete"

    @property
    def keyed(self) -> bool:
        """Whether the mode matches existing records on ``keys``."""
        return self in _KEYED

    @property
    def destructive(self) -> bool:
        """Whether the mode removes or overwrites records (plan/apply gated)."""
        return self in _DESTRUCTIVE


_KEYED = frozenset({WriteMode.MERGE, WriteMode.REPLACE, WriteMode.DELETE})
_DESTRUCTIVE = frozenset({WriteMode.REPLACE, WriteMode.DELETE})


@dataclass(frozen=True, slots=True)
class WriteOperation:
    """
    A normalized, validated write specification.

    Attributes:

        mode: How incoming records reconcile with the destination.
        keys: The match keys for a keyed mode; empty otherwise.
        idempotency_key: The dedupe key for an ``append``; empty otherwise.

    """

    mode: WriteMode
    keys: tuple[str, ...] = ()
    idempotency_key: tuple[str, ...] = ()


def _as_tuple(value: KeyLike | None) -> tuple[str, ...]:
    """Normalizes ``value`` into a tuple of names, wrapping a bare string."""
    if value is None:
        result = ()
    elif isinstance(value, str):
        result = (value,)
    else:
        result = tuple(value)

    return result


def write_operation(
    mode: WriteMode | str,
    *,
    keys: KeyLike | None = None,
    idempotency_key: KeyLike | None = None,
) -> WriteOperation:
    """
    Validates and normalizes a write operation for ``mode``.

    Args:

        mode: The write mode, as a ``WriteMode`` or its string value.
        keys: The match keys for a keyed mode (``merge``/``replace``/``delete``).
        idempotency_key: The dedupe key for an ``append``.

    Returns:

        The normalized, validated write specification.

    Raises:

        ValueError: When ``mode`` is unknown, a keyed mode is missing ``keys`` or
            supplies ``idempotency_key``, or ``append`` supplies ``keys``.

    """
    resolved = WriteMode(mode)
    match_keys = _as_tuple(keys)
    idem = _as_tuple(idempotency_key)

    if resolved.keyed and not match_keys:
        raise ValueError(f"the '{resolved.value}' write mode requires 'keys'")

    if resolved.keyed and idem:
        raise ValueError(f"the '{resolved.value}' write mode forbids 'idempotency_key'")

    if not resolved.keyed and match_keys:
        raise ValueError(f"the '{resolved.value}' write mode forbids 'keys'")

    return WriteOperation(resolved, match_keys, idem)


__all__ = ["KeyLike", "WriteMode", "WriteOperation", "write_operation"]
