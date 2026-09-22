"""Mapping normalization and validation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.base.exceptions import InvalidPipelineError
from riko.types._guards import is_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping


def require_mapping(value: object, what: str) -> Mapping[str, object]:
    """Narrows a value to a mapping or rejects it as malformed structure."""
    if not is_mapping(value):
        raise InvalidPipelineError(f"{what} must be a mapping")

    return value


def invert_dict[K, V](d: dict[K, V]) -> dict[V, K]:
    """
    Swaps a dict's keys and values.

    Args:

        d: The dict to invert; its values must be hashable and unique.

    Returns:

        A new dict mapping each value back to its key.

    Examples:

        >>> invert_dict({"a": 1, "b": 2})
        {1: 'a', 2: 'b'}

    """
    return {v: k for k, v in d.items()}


def validate_dict[K, V](item: object | dict[K, V]) -> dict[K, V]:
    """
    Copies a mapping into a plain dict.

    Args:

        item: Value expected to satisfy Riko's mapping guard.

    Returns:

        A plain dict containing the mapping's items.

    Raises:

        TypeError: When ``item`` is not mapping-like.

    Examples:

        >>> validate_dict({"a": 1})
        {'a': 1}
        >>> validate_dict([("a", 1)])
        Traceback (most recent call last):
        ...
        TypeError: Expected a mapping, got list

    """
    if not is_mapping(item):
        raise TypeError(f"Expected a mapping, got {type(item).__name__}")

    return dict(item)
