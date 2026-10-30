"""
Immutable mappings and the helpers that build them.

Holds ``FrozenDict``, the recursive ``freeze``/``freeze_json``/``thaw`` helpers,
``normalize_mapping``, ``instances_freezer``, and the attrs converters that check
mappings and freeze them into ``FrozenDict``s.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, cast, final, overload

import attrs
from typing_extensions import TypeForm, TypeIs

from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import (
    is_dataclass_inst,
    is_known_sequence,
    is_mapping,
    require_mapping,
)
from riko.base._iterutils import map_keys_and_values, map_values, noop
from riko.base._require_guards import require_finite, require_instances, require_str

if TYPE_CHECKING:
    from ._workflow import GraphEdge
    from .modules import AnyConfRule

type FrozenJSON = (
    bool
    | int
    | float
    | str
    | tuple[FrozenJSON, ...]
    | FrozenDict[str, FrozenJSON]
    | None
)

type FrozenConf = FrozenDict[str, FrozenJSON]
type FrozenParams = FrozenDict[str, FrozenJSON]
type FrozenPolicy = FrozenDict[str, FrozenJSON]
type FrozenTupleMapping = FrozenDict[str, tuple[GraphEdge, ...]]
type FrozenSetMapping = FrozenDict[str, frozenset[str]]
type Freezer[FV] = Callable[[Mapping[str, object]], FrozenDict[str, FV]]
type MappingConverter[FV] = Callable[[Mapping[str, object]], FrozenDict[str, FV]]
type TypeConverter[T, FV] = Callable[[T], FrozenDict[str, FV]]

type OptionalMappingConverter[FV] = Callable[
    [Mapping[str, object] | None], FrozenDict[str, FV]
]

type OptionalTypeConverter[T, FV] = Callable[[T | None], FrozenDict[str, FV]]


def is_conf_rule(value: object) -> TypeIs[AnyConfRule]:
    return is_dataclass_inst(value) and type(value).__name__.endswith("ConfRule")


@overload
def _freeze_value(value: object, json_native: Literal[True]) -> FrozenJSON: ...
@overload
def _freeze_value(value: object, json_native: bool = ...) -> object: ...
def _freeze_value(value: object, json_native: bool = False) -> object:
    """Freezes built-in containers recursively, optionally allowing only JSON."""
    is_named_tuple = isinstance(value, tuple) and hasattr(value, "_fields")

    if value is None or isinstance(value, (str, int)):
        result = value
    elif isinstance(value, float):
        result = require_finite(value) if json_native else value
    elif isinstance(value, FrozenDict) and not json_native:
        result = value
    elif is_mapping(value):
        result = FrozenDict.from_frozen(_freeze_items(value, json_native))
    elif is_named_tuple and not json_native:
        result = value
    elif is_known_sequence(value):
        result = tuple(_freeze_value(item, json_native) for item in value)
    elif json_native and is_conf_rule(value):
        result = FrozenDict.from_frozen(_freeze_items(asdict(value), json_native))
    elif json_native:
        raise InvalidPipelineError(f"{type(value).__name__} is not JSON-native")
    elif isinstance(value, set):
        result = frozenset(value)
    else:
        result = value

    return result


def _freeze_items[K, V](
    data: Mapping[K, V] | Iterable[tuple[K, V]], json_native: bool = False
) -> dict[K | str, object]:
    """Freezes each value of a mapping or of key/value pairs into a new dict."""
    item = data if is_mapping(data) else dict(data)
    require = partial(require_str, what="mapping key")
    check: Callable[[K], K | str] = require if json_native else noop
    freeze_item = partial(_freeze_value, json_native=json_native)
    return map_keys_and_values(check, freeze_item, item)


@final
@attrs.define(frozen=True, slots=True, eq=False, repr=False, init=False)
class FrozenDict[K, V](Mapping[K, V]):
    """
    A read-only mapping whose built-in container values are frozen too.

    It copies its source, a mapping or key/value pairs, and freezes the values as
    ``freeze`` does, so it never changes once built. It compares equal to any
    mapping with the same items, hashes when its values do, and merges with ``|``
    into a new ``FrozenDict``.

    Examples:

        >>> frozen = FrozenDict({"a": [1, {"b": 2}]})
        >>> frozen["a"]
        (1, FrozenDict({'b': 2}))
        >>> frozen == {"a": (1, {"b": 2})}
        True

    """

    _data: Mapping[K, V]

    def __init__(self, data: Mapping[K, V] | Iterable[tuple[K, V]] = (), /) -> None:
        frozen = data._data if isinstance(data, FrozenDict) else _freeze_items(data)
        object.__setattr__(self, "_data", dict(frozen))

    def __getitem__(self, key: K) -> V:
        return self._data[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({dict(self._data)!r})"

    def __hash__(self) -> int:
        return hash(frozenset(self._data.items()))

    def __or__(self, other: object) -> FrozenDict[K, V]:
        merged = (
            FrozenDict({**self._data, **other}) if isinstance(other, Mapping) else None
        )
        return NotImplemented if merged is None else merged

    def __ror__(self, other: object) -> FrozenDict[K, V]:
        merged = (
            FrozenDict({**other, **self._data}) if isinstance(other, Mapping) else None
        )
        return NotImplemented if merged is None else merged

    @classmethod
    def from_frozen(cls, data: Mapping[K, V]) -> FrozenDict[K, V]:
        """Wraps ``data`` whose values the caller has already frozen."""
        frozen = object.__new__(cls)
        object.__setattr__(frozen, "_data", dict(data))  # noqa: PLC2801
        return frozen


@overload
def freeze(value: None) -> None: ...
@overload
def freeze[K, V](value: Mapping[K, list[V]]) -> FrozenDict[K, tuple[V]]: ...
@overload
def freeze[K, V](value: Mapping[K, set[V]]) -> FrozenDict[K, frozenset[V]]: ...
@overload
def freeze[K, V](value: Mapping[K, V]) -> FrozenDict[K, V]: ...
@overload
def freeze[T](value: list[T] | tuple[T, ...]) -> tuple[T, ...]: ...
@overload
def freeze[T](value: set[T] | frozenset[T]) -> frozenset[T]: ...
@overload
def freeze[T](value: T) -> T: ...
def freeze(value: object) -> object:
    """
    Freezes the built-in containers in a value, recursively.

    Mappings become ``FrozenDict``s, lists and tuples become tuples, and sets become
    frozensets. A ``FrozenDict``, a named tuple, and any other object, such as a
    caller-owned client, are kept as is.

    Args:

        value: The value to freeze.

    Returns:

        The value with every built-in container frozen.

    Examples:

        >>> from collections import namedtuple
        >>>
        >>> frozen = freeze({"a": [1, {"b": {2}}], "c": object})
        >>> frozen["a"]
        (1, FrozenDict({'b': frozenset({2})}))
        >>> frozen["c"]
        <class 'object'>
        >>> Point = namedtuple("Point", "x y")
        >>> freeze(Point(1, [2]))
        Point(x=1, y=[2])

    """
    return _freeze_value(value)


@overload
def freeze_json(value: None) -> None: ...
@overload
def freeze_json(value: Mapping[str, object]) -> FrozenDict[str, FrozenJSON]: ...
@overload
def freeze_json(value: Mapping[object, object]) -> FrozenDict[str, FrozenJSON]: ...
@overload
def freeze_json(value: object) -> FrozenJSON: ...
def freeze_json(value: object) -> FrozenJSON:
    """
    Freezes a value into an immutable JSON-native tree.

    Mappings become string-keyed ``FrozenDict``s and lists and tuples become tuples,
    recursively. A value with no JSON form (a set, ``Decimal``, date, bytes,
    non-finite float, non-string key, or any other object) is rejected, so a
    workflow never carries a value that cannot round-trip through JSON.

    Args:

        value: The value to freeze.

    Returns:

        The frozen JSON-native value.

    Raises:

        InvalidPipelineError: When the value is not JSON-native.

    Examples:

        >>> frozen = freeze_json({"a": [1, {"b": 2}]})
        >>> frozen["a"]
        (1, FrozenDict({'b': 2}))
        >>> freeze_json({"a": {1, 2}})
        Traceback (most recent call last):
        ...
        riko.base.exceptions.InvalidPipelineError: ...d pipeline: set is not JSON-native

    """
    return _freeze_value(value, json_native=True)


@overload
def thaw[K, V](value: Mapping[K, V]) -> dict[K, V]: ...
@overload
def thaw(value: object) -> object: ...
def thaw(value: object) -> object:
    """
    Copies a value's containers into plain mutable ones, recursively.

    Any mapping, such as a ``FrozenDict`` or ``DotDict``, becomes a dict, a tuple a
    list, and a frozenset a set, so ``thaw`` undoes ``freeze``. A named tuple and any
    other object are kept as is.

    Args:

        value: The value to copy.

    Returns:

        A mutable copy of the value.

    Examples:

        >>> from types import MappingProxyType
        >>>
        >>> thaw(freeze({"a": [1, {"b": 2}]}))
        {'a': [1, {'b': 2}]}
        >>> thaw(MappingProxyType({"a": MappingProxyType({"b": 2})}))
        {'a': {'b': 2}}
        >>> thaw(frozenset({1}))
        {1}

    """
    if is_mapping(value):
        result = map_values(thaw, value)
    elif type(value) is tuple:
        result = [thaw(item) for item in value]
    elif type(value) is frozenset:
        result = set(value)
    else:
        result = value

    return result


def instances_freezer[T](
    cls: type[T], what: str, *, error: type[Exception] = InvalidPipelineError
) -> Freezer[T]:
    """
    Builds a freezer that requires every value of a mapping to be a ``cls`` instance.

    Pass it to ``mapping_converter`` or ``optional_mapping_converter`` for a field
    whose values must all share one type.

    Args:

        cls: The class every value must be an instance of.
        what: The name used in error messages.

    Kwargs:

        error: The exception raised for a value that isn't a ``cls``.

    Returns:

        A freezer that returns the checked mapping as a ``FrozenDict``.

    Examples:

        >>> freezer = instances_freezer(int, "count")
        >>> freezer({"a": 1})
        FrozenDict({'a': 1})
        >>> freezer({"b": "x"})
        Traceback (most recent call last):
        ...
        riko.base.exceptions.InvalidPipelineError: ...'b' must be of type int, not str

    """

    def freezer(value: Mapping[str, object]) -> FrozenDict[str, T]:
        return FrozenDict(require_instances(cls, value, what, error=error))

    return freezer


@overload
def mapping_converter[FV](
    freezer: Freezer[FV], *, what: str = ..., error: type[Exception] = ...
) -> MappingConverter[FV]: ...
@overload
def mapping_converter[FV, T](
    freezer: Freezer[FV],
    accepted: TypeForm[T],
    /,
    *,
    what: str = ...,
    error: type[Exception] = ...,
) -> TypeConverter[T, FV]: ...
def mapping_converter[FV](
    freezer: Freezer[FV],
    *_: object,
    what: str = "value",
    error: type[Exception] = InvalidPipelineError,
) -> Callable[..., FrozenDict[str, FV]]:
    """
    Builds an attrs converter that freezes a required mapping and rejects anything else.

    Pass it as a field's only ``converter`` to retain the ``accepted`` type signature
    (pyright can't infer the type signature when using a list as an attrs converter).

    Args:

        freezer: Freezes the checked mapping, e.g. ``freeze_json``.

    Kwargs:

        what: The name used in the error message.
        error: The exception raised for a value that isn't a mapping.

    Returns:

        A one-argument converter that returns a ``FrozenDict``.

    Examples:

        >>> from riko.types._frozendict import freeze_json
        >>>
        >>> converter = mapping_converter(freeze_json, what="inputs")
        >>> converter({"ids": [1]})
        FrozenDict({'ids': (1,)})
        >>> converter("abc")
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...inputs must be a mapping

    """

    def converter(value: object) -> FrozenDict[str, FV]:
        return freezer(require_mapping(value, what, error=error))

    return converter


@overload
def normalize_mapping[T](
    item: Mapping[str, T] | None, what: str = ..., *, strict: Literal[False] = ...
) -> dict[str, T]: ...
@overload
def normalize_mapping(
    item: object, what: str = ..., *, strict: Literal[True]
) -> dict[str, object]: ...
def normalize_mapping(
    item: object, what: str = "value", *, strict: bool = False
) -> dict[str, Any]:
    """
    Normalizes an optional mapping to a new ``dict``, empty for ``None``.

    Args:

        item: The mapping to copy, or ``None``.
        what: The name used in the error message when ``strict``.

    Kwargs:

        strict: Whether anything other than a mapping or ``None`` raises.

    Returns:

        A new ``dict`` with ``item``'s entries.

    Raises:

        InvalidPipelineError: If ``strict`` and ``item`` is not a mapping.

    Examples:

        >>> normalize_mapping({"a": 1}), normalize_mapping(None)
        ({'a': 1}, {})
        >>> normalize_mapping([("a", 1)], "inputs", strict=True)
        Traceback (most recent call last):
        ...
        riko.base.exceptions.InvalidPipelineError: ...inputs must be a mapping

    """
    if item is None:
        result: dict[str, Any] = {}
    elif strict:
        result = dict(require_mapping(item, what))
    else:
        result = dict(cast("Mapping[str, object]", item))

    return result


@overload
def optional_mapping_converter[FV](
    freezer: Freezer[FV],
    *,
    default: Mapping[str, object] | None = ...,
    what: str = ...,
    error: type[Exception] = ...,
) -> OptionalMappingConverter[FV]: ...
@overload
def optional_mapping_converter[FV, T](
    freezer: Freezer[FV],
    accepted: TypeForm[T],
    /,
    *,
    default: Mapping[str, object] | None = ...,
    what: str = ...,
    error: type[Exception] = ...,
) -> OptionalTypeConverter[T, FV]: ...
def optional_mapping_converter[FV](
    freezer: Freezer[FV],
    *_: object,
    default: Mapping[str, object] | None = None,
    what: str = "value",
    error: type[Exception] = InvalidPipelineError,
) -> Callable[..., FrozenDict[str, FV]]:
    """
    Builds an attrs converter to freeze mappings or ``None`` and reject anything else.

    Like ``mapping_converter``, pass it as a field's only ``converter`` to retain the
    ``accepted`` type signature (pyright can't infer the type signature when using a
    list as an attrs converter).

    Args:

        freezer: Freezes the checked mapping, e.g. ``freeze_json``.

    Kwargs:

        default: The mapping to freeze for ``None`` (default: an empty mapping).
        what: The name used in the error message (default: "value").
        error: The exception raised for a value that isn't a mapping or ``None``.

    Returns:

        A one-argument converter that returns a ``FrozenDict``.

    Examples:

        >>> from riko.types._frozendict import freeze_json
        >>>
        >>> converter = optional_mapping_converter(freeze_json)
        >>> converter(None)
        FrozenDict({})
        >>> converter = optional_mapping_converter(freeze_json, default={"a": 1})
        >>> converter(None)
        FrozenDict({'a': 1})
        >>> converter({"b": 2})
        FrozenDict({'b': 2})

    """
    item: Mapping[str, object] = normalize_mapping(default)

    def converter(value: object) -> FrozenDict[str, FV]:
        mapped = item if value is None else require_mapping(value, what, error=error)
        return freezer(mapped)

    return converter
