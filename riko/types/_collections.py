"""Collection, mapping, and nested value typing aliases."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from decimal import Decimal
from math import isinf, isnan
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, cast, get_origin, overload

import attrs
from attrs import Attribute, AttrsInstance

from riko.base.exceptions import InvalidPipelineError

if TYPE_CHECKING:
    from riko.parsing._dotdict import DotDict

    from ._scalars import BasicValue, PrimitiveValue

type FrozenJSON = (
    bool
    | int
    | float
    | str
    | tuple[FrozenJSON, ...]
    | MappingProxyType[str, FrozenJSON]
    | None
)

type FrozenMap[T] = MappingProxyType[str, T]
type JSONSchema = FrozenMap[FrozenJSON]
type Inputs = Mapping[str, str | int | bool]
type InputSource = Mapping[str, str]
type Key = str | InputSource
type AttrsValidator[T] = Callable[[AttrsInstance, Attribute[Any], T], None]

# Args
type BasicMapping = Mapping[str, BasicValue]
type BasicArg = BasicValue | BasicMapping | Sequence[BasicValue]

# Returns
type BasicDict = (
    dict[str, str]
    | dict[str, bool]
    | dict[str, int]
    | dict[str, Decimal]
    | dict[str, float]
)
type BasicList = list[str] | list[bool] | list[int] | list[Decimal] | list[float]
type BasicReturn = BasicValue | BasicDict | BasicList | tuple[BasicValue, ...]

type Stringy = str | StringyList | StringyDict
type StringyDict = dict[str, Stringy]
type StringyList = list[Stringy]

type RikoDict = (
    BasicDict
    | StringyDict
    | dict[str, PrimitiveValue]
    | dict[str, BasicDict]
    | dict[str, BasicList]
    | "DotDict[PrimitiveValue]"
)
type RikoList = BasicList | list[BasicDict] | StringyList
type RikoValue = PrimitiveValue | RikoList


@overload
def def_from_require[T, R](  # noqa: E704
    require: Callable[[T], R], default: None = ...
) -> Callable[[T], R | None]: ...
@overload  # noqa: E302
def def_from_require[T, D, R](  # noqa: E704
    require: Callable[[T], R], default: D
) -> Callable[[T], R | D]: ...
@overload  # noqa: E302
def def_from_require[T, R](  # noqa: E704
    require: Callable[[T], R], default: None = ..., what: str | None = ...
) -> Callable[[T], R | None]: ...
@overload  # noqa: E302
def def_from_require[T, D, R](  # noqa: E704
    require: Callable[[T], R], default: D, what: str | None = ...
) -> Callable[[T], R | D]: ...
def def_from_require[T, D, R](  # noqa: E302
    require: Callable[[T], R], default: D | None = None, what: str | None = None
) -> Callable[[T], R | D | None]:
    def optional(value: T) -> R | D | None:
        kwargs = {} if what is None else {"what": what}
        return default if value is None else require(value, **kwargs)

    return optional


def require_str(value: object, what: str | None = "value") -> str:
    """Reads the required registered-name field off a node's authoring mapping."""
    if not isinstance(value, str):
        raise InvalidPipelineError(f"{what} must be a str")

    return value


def require_strlike(value: object, what: str | None = "value") -> str | tuple[str, ...]:
    """Reads the required registered-name field off a node's authoring mapping."""
    if isinstance(value, str):
        valid = True
    elif isinstance(value, Iterable):
        value = tuple(value)
        valid = all(isinstance(v, str) for v in value)
    else:
        valid = False

    if not valid:
        raise InvalidPipelineError(f"{what} must be a str or iterable of strs")

    return cast("str | tuple[str, ...]", value)


def require_finite(value: float, what: str | None = "value") -> float:
    if isnan(value) or isinf(value):
        msg = f"non-finite float is not JSON-native: {value!r}"
        raise InvalidPipelineError(msg)

    return value


def require_binding(
    value: object, what: str | None = "value"
) -> str | Mapping[object, object] | Iterable[object]:
    if not isinstance(value, (str, Mapping, Iterable)):
        raise TypeError(f"{what} must be a either str, mapping, iterable, or None")

    return value


def freeze_mapping[K, V](value: Mapping[K, V]) -> MappingProxyType[K, V]:
    """Copies ``value`` into a read-only mapping detached from its source."""
    return MappingProxyType(dict(value))


@overload
def freeze_value(value: None) -> None: ...  # noqa: E704
@overload  # noqa: E302
def freeze_value(value: Mapping[str, object]) -> JSONSchema: ...  # noqa: E704
@overload  # noqa: E302
def freeze_value(value: Mapping[object, object]) -> JSONSchema: ...  # noqa: E704
def freeze_value(value: object) -> FrozenJSON:  # noqa: E302
    """
    Deep-freezes a value into an immutable JSON-native tree.

    Mappings become read-only string-keyed mappings and sequences become tuples,
    recursively, detached from their source. A value with no JSON-native form (a set,
    ``Decimal``, date, bytes, non-finite float, or non-string key) is rejected so a
    canonical spec never carries a value that cannot round-trip through JSON.

    Returns:

        The frozen JSON-native value.

    Raises:

        InvalidPipelineError: When the value is not JSON-native.

    Examples:

        >>> frozen = freeze_value({"a": [1, {"b": 2}]})
        >>> frozen["a"]
        (1, mappingproxy({'b': 2}))

    """
    if value is None or isinstance(value, (str, bool, int)):
        result: FrozenJSON = value
    elif isinstance(value, float):
        result = require_finite(value)
    elif isinstance(value, Mapping):
        items = value.items()
        result = freeze_mapping({require_str(k): freeze_value(v) for k, v in items})
    elif isinstance(value, (list, tuple)):
        result = tuple(map(freeze_value, value))
    else:
        raise InvalidPipelineError(f"value is not JSON-native: {type(value).__name__}")

    return result


def deep_freeze_mapping(value: Mapping[str, object]) -> JSONSchema:
    """Deep-freezes declared inputs into read-only JSON-native schema mappings."""
    return freeze_value(dict(value))


def _is_classvar(annotation: object) -> bool:
    if isinstance(annotation, str):
        text = annotation.strip()
        result = text == "ClassVar" or text.startswith(("ClassVar[", "typing.ClassVar"))
    else:
        result = annotation is ClassVar or get_origin(annotation) is ClassVar

    return result


def field_names(cls: type) -> frozenset[str]:
    """
    Names the fields of an attrs or dataclass ``cls``, including ``ClassVar`` members.

    Mimics dataclass's ``__dataclass_fields__`` which retains ``ClassVar`` attributes.

    Args:

        cls: An attrs-decorated or dataclass type.

    Returns:

        The instance field names together with every ``ClassVar`` member name.

    Examples:

        >>> from dataclasses import dataclass
        >>> from typing import ClassVar
        >>> from riko.types._collections import field_names
        >>>
        >>> @dataclass
        ... class Point:
        ...     kind: ClassVar[str] = "cartesian"
        ...     x: int = 0
        ...     y: int = 0
        >>>
        >>> sorted(field_names(Point))
        ['kind', 'x', 'y']

    """
    if attrs.has(cls):
        names = set(attrs.fields_dict(cls))
    elif is_dataclass(cls):
        names = {member.name for member in fields(cls)}
    else:
        names = set()

    for _class in cls.__mro__:
        annotations = getattr(_class, "__annotations__", {})
        names.update(name for name, hint in annotations.items() if _is_classvar(hint))

    return frozenset(names)


class FreezeMapping[K, V]:
    def __call__(self, value: Mapping[K, V]) -> MappingProxyType[K, V]:
        return freeze_mapping(value)
