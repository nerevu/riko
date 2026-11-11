"""
Immutable mappings and the helpers that build them.

Holds ``FrozenDict``, the recursive ``freeze``/``json_freeze``/``thaw`` helpers,
``normalize_mapping``, ``instances_freezer``, and the attrs converters that check
mappings and freeze them into ``FrozenDict``s.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from itertools import repeat
from typing import TYPE_CHECKING, Literal, final, overload

import attrs
from typing_extensions import TypeForm, TypeIs

from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_keys_and_values, map_values
from riko.base._guards import (
    is_dataclass_inst,
    is_known_sequence,
    is_mapping,
    require_mapping,
)
from riko.base._recordutils import serialize_dataclass
from riko.base._require_guards import require_finite, require_instances, require_str

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

    from riko.definitions._nodes import RikoNode

    from ._workflow import Endpoint, NodeId, PortEdge, WorkflowEdge
    from ._wrappers import Func
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

type JSONValue = (
    bool | int | float | str | Sequence[JSONValue] | Mapping[str, JSONValue] | None
)

type FrozenConf = FrozenDict[str, FrozenJSON]
type FrozenInputs = FrozenDict[str, FrozenJSON]
type FrozenInputSchema = FrozenDict[str, FrozenJSON]
type FrozenInputSchemas = FrozenDict[str, FrozenInputSchema]
type FrozenOutputs = FrozenDict[str, Endpoint]
type FrozenNodes = FrozenDict[NodeId, RikoNode]
type FrozenPortEdges = tuple[PortEdge, ...]
type FrozenWorkflowEdges = tuple[WorkflowEdge, ...]
type FrozenResources = tuple[str, ...]
type FrozenParams = FrozenDict[str, FrozenJSON]
type FrozenPolicy = FrozenDict[str, FrozenJSON]
type FrozenWorkflowEdgeCollection = FrozenDict[str, FrozenWorkflowEdges]
type FrozenSetMapping = FrozenDict[str, frozenset[str]]
type Freezer[FV] = Callable[[Mapping[str, object]], FrozenDict[str, FV]]
type MappingConverter[FV] = Callable[[Mapping[str, object]], FrozenDict[str, FV]]
type TypeConverter[T, FV] = Callable[[T], FrozenDict[str, FV]]

type OptionalMappingConverter[FV] = Callable[
    [Mapping[str, object] | None], FrozenDict[str, FV]
]

type OptionalTypeConverter[T, FV] = Callable[[T | None], FrozenDict[str, FV]]
type SortKey[T] = Callable[[T], SupportsRichComparison] | None


def is_conf_rule(value: object) -> TypeIs[AnyConfRule]:
    return is_dataclass_inst(value) and type(value).__name__.endswith("ConfRule")


@overload
def _freeze_value(value: object, json_native: Literal[True]) -> FrozenJSON: ...
@overload
def _freeze_value[T](
    value: T, json_native: Literal[True], *, key: SortKey[T] | None = ...
) -> FrozenJSON: ...
@overload
def _freeze_value(value: object, json_native: bool = ...) -> object: ...
@overload
def _freeze_value[T](
    value: T, json_native: bool = ..., *, value_func: Callable[[T], object] | None = ...
) -> object: ...
@overload
def _freeze_value[T](
    value: T,
    *,
    key: SortKey[T] | None = ...,
    value_func: Callable[[T], object] | None = ...,
    mapping_value_func: Func[object] | None = ...,
) -> object: ...
@overload
def _freeze_value[K, V](
    value: Mapping[K, V],
    json_native: bool = ...,
    *,
    key: SortKey[K] | None = ...,
    mapping_value_func: Callable[[V], object] | None = ...,
) -> object: ...
def _freeze_value(
    value: object,
    json_native: bool = False,
    *,
    key: Func[SupportsRichComparison] | None = None,
    value_func: Func[object] | None = None,
    mapping_value_func: Func[object] | None = None,
) -> object:
    """Freezes built-in containers recursively, optionally allowing only JSON."""
    is_named_tuple = isinstance(value, tuple) and hasattr(value, "_fields")

    if value_func is not None:
        value = value_func(value)

    if value is None or isinstance(value, (str, int)):
        result = value
    elif isinstance(value, float):
        result = require_finite(value) if json_native else value
    elif isinstance(value, FrozenDict) and not json_native:
        result = value
    elif is_mapping(value):
        if key is None:
            ordered = value
        else:
            ordered = {k: value[k] for k in sorted(value, key=key)}

        result = FrozenDict.from_frozen(
            _freeze_items(ordered, json_native, mapping_value_func=mapping_value_func)
        )
    elif is_named_tuple and not json_native:
        result = value
    elif is_known_sequence(value):
        ordered = value if key is None else sorted(value, key=key)
        result = tuple(map(_freeze_value, ordered, repeat(json_native)))
    elif json_native and is_conf_rule(value):
        _value = serialize_dataclass(value, compact=False)
        result = FrozenDict.from_frozen(
            _freeze_items(_value, json_native, mapping_value_func=mapping_value_func)
        )
    elif json_native:
        raise InvalidPipelineError(f"{type(value).__name__} is not JSON-native")
    elif isinstance(value, set):
        result = frozenset(value)
    else:
        result = value

    return result


def _freeze_items[K, V](
    data: Mapping[K, V] | Iterable[tuple[K, V]],
    json_native: bool = False,
    mapping_value_func: Callable[[V], object] | None = None,
) -> dict[K | str, object]:
    """Freezes each value of a mapping or of key/value pairs into a new dict."""
    value_func = mapping_value_func
    item = data if is_mapping(data) else dict(data)

    def check(value: K) -> K | str:
        return require_str(value, what="mapping key") if json_native else value

    def freeze_item(value: V):
        return _freeze_value(value, json_native=json_native, value_func=value_func)

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

    def __or__(self, other: Mapping[K, V] | object) -> FrozenDict[K, V]:
        merged = FrozenDict({**self._data, **other}) if is_mapping(other) else None
        return NotImplemented if merged is None else merged

    def __ror__(self, other: Mapping[K, V] | object) -> FrozenDict[K, V]:
        merged = FrozenDict({**other, **self._data}) if is_mapping(other) else None
        return NotImplemented if merged is None else merged

    @classmethod
    def from_frozen(cls, data: Mapping[K, V]) -> FrozenDict[K, V]:
        """Wraps ``data`` whose values the caller has already frozen."""
        frozen = object.__new__(cls)
        object.__setattr__(frozen, "_data", dict(data))  # noqa: PLC2801
        return frozen


EMPTY_INPUT_SCHEMAS: FrozenInputSchemas = FrozenDict()


@overload
def freeze(value: None) -> None: ...
@overload
def freeze[K, J, V](
    value: Mapping[K, Mapping[J, V]],
) -> FrozenDict[K, FrozenDict[J, V]]: ...
@overload
def freeze[K, V](value: Mapping[K, list[V]]) -> FrozenDict[K, tuple[V, ...]]: ...
@overload
def freeze[K, V](
    value: Mapping[K, set[V]], *, key: SortKey[K] | None = ...
) -> FrozenDict[K, frozenset[V]]: ...
@overload
def freeze[K, V, R](
    value: Mapping[K, V],
    *,
    key: SortKey[K] | None = ...,
    mapping_value_func: Callable[[V], R],
) -> FrozenDict[K, R]: ...
@overload
def freeze[K, V](
    value: Mapping[K, V], *, key: SortKey[K] | None = ...
) -> FrozenDict[K, V]: ...
@overload
def freeze[K, V](
    value: list[dict[K, V]] | tuple[Mapping[K, V], ...],
) -> tuple[FrozenDict[K, V], ...]: ...
@overload
def freeze[T](value: list[list[T]]) -> tuple[tuple[T, ...], ...]: ...
@overload
def freeze[T](value: list[T] | tuple[T, ...]) -> tuple[T, ...]: ...
@overload
def freeze[T](value: set[T] | frozenset[T]) -> frozenset[T]: ...
@overload
def freeze[T](value: T) -> T: ...
def freeze(
    value: object,
    *,
    key: Func[SupportsRichComparison] | None = None,
    mapping_value_func: Func[object] | None = None,
) -> object:
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
    return _freeze_value(value, key=key, mapping_value_func=mapping_value_func)


@overload
def json_freeze(value: None) -> None: ...
@overload
def json_freeze(value: Mapping[str, object]) -> FrozenDict[str, FrozenJSON]: ...
@overload
def json_freeze(value: Mapping[object, object]) -> FrozenDict[str, FrozenJSON]: ...
@overload
def json_freeze(value: object) -> FrozenJSON: ...
def json_freeze(value: object, key: SortKey[object] | None = None) -> FrozenJSON:
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

        >>> frozen = json_freeze({"a": [1, {"b": 2}]})
        >>> frozen["a"]
        (1, FrozenDict({'b': 2}))
        >>> json_freeze({"a": {1, 2}})
        Traceback (most recent call last):
        ...
        riko.exceptions.InvalidPipelineError: ...d pipeline: set is not JSON-native

    """
    return _freeze_value(value, True, key=key)


@overload
def thaw[K, V](value: Mapping[K, V]) -> dict[K, V]: ...
@overload
def thaw(value: object) -> object: ...
def thaw(value: object) -> object:
    """
    Copies a value's containers into plain mutable ones, recursively.

    Undoes ``freeze``: mappings become dicts, tuples become lists, and frozensets become
    sets. Named tuples and any other objects are kept as is.

    Args:

        value: The value to convert.

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
        riko.exceptions.InvalidPipelineError: ...'b' must be of type int, not str

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
    freezer: Callable[[T], FrozenDict[str, FV]],
    accepted: TypeForm[T],
    /,
    *,
    what: str = ...,
    error: type[Exception] = ...,
) -> TypeConverter[T, FV]: ...
def mapping_converter[FV](
    freezer: Func[FrozenDict[str, FV]],
    *_: object,
    what: str = "value",
    error: type[Exception] = InvalidPipelineError,
) -> Func[FrozenDict[str, FV]]:
    """
    Builds an attrs converter that freezes a required mapping and rejects anything else.

    Pass it as a field's only ``converter`` to retain the ``accepted`` type signature
    (pyright can't infer the type signature when using a list as an attrs converter).

    Args:

        freezer: Freezes the checked mapping, e.g. ``json_freeze``.
        accepted: The type the converter accepts, e.g. ``Conf``.

    Kwargs:

        what: The name used in the error message.
        error: The exception raised for a value that isn't a mapping.

    Returns:

        A one-argument converter that returns a ``FrozenDict``.

    Examples:

        >>> from riko.types._frozendict import json_freeze
        >>>
        >>> converter = mapping_converter(json_freeze, what="inputs")
        >>> converter({"ids": [1]})
        FrozenDict({'ids': (1,)})
        >>> converter("abc")
        Traceback (most recent call last):
            ...
        riko.exceptions.InvalidPipelineError: ...inputs must be a mapping, not str

    """

    def converter(value: object) -> FrozenDict[str, FV]:
        return freezer(require_mapping(value, what, error=error))

    return converter


def normalize_mapping[T](item: Mapping[str, T] | None) -> dict[str, T]:
    """
    Normalizes an optional mapping to a new ``dict`` (empty for ``None``).

    Args:

        item: The mapping to copy, or ``None``.

    Returns:

        A new ``dict`` with ``item``'s entries.

    Examples:

        >>> normalize_mapping({"a": 1}), normalize_mapping(None)
        ({'a': 1}, {})

    """
    return {} if item is None else dict(item)


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
) -> Func[FrozenDict[str, FV]]:
    """
    Builds an attrs converter to freeze mappings or ``None`` and reject anything else.

    Like ``mapping_converter``, pass it as a field's only ``converter`` to retain the
    ``accepted`` type signature (pyright can't infer the type signature when using a
    list as an attrs converter).

    Args:

        freezer: Freezes the checked mapping, e.g. ``json_freeze``.

    Kwargs:

        default: The mapping to freeze for ``None`` (default: an empty mapping).
        what: The name used in the error message (default: "value").
        error: The exception raised for a value that isn't a mapping or ``None``.

    Returns:

        A one-argument converter that returns a ``FrozenDict``.

    Examples:

        >>> from riko.types._frozendict import json_freeze
        >>>
        >>> converter = optional_mapping_converter(json_freeze)
        >>> converter(None)
        FrozenDict({})
        >>> converter = optional_mapping_converter(json_freeze, default={"a": 1})
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
