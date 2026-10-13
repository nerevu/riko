"""Collection, mapping, and nested value typing aliases."""

from __future__ import annotations

import ast
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import Field, asdict, fields, is_dataclass
from decimal import Decimal
from functools import partial
from math import isinf, isnan
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    Protocol,
    cast,
    final,
    get_origin,
    is_typeddict,
    overload,
    runtime_checkable,
)

import attrs
from attrs import Attribute, AttrsInstance, validators
from typing_extensions import TypeForm

from riko.base._iterutils import map_values
from riko.base.exceptions import InvalidPipelineError

from ._guards import is_attrs_inst, is_conf_rule, is_mapping, require_mapping

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.parsing._dotdict import DotDict

    from ._enums import StrLike
    from ._scalars import BasicValue, PrimitiveValue
    from ._workflow import GraphEdge

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
type FrozenOptions = FrozenDict[str, FrozenJSON]
type FrozenParams = FrozenDict[str, FrozenJSON]
type FrozenPolicy = FrozenDict[str, FrozenJSON]
type FrozenTupleMapping = FrozenDict[str, tuple[GraphEdge, ...]]
type FrozenSetMapping = FrozenDict[str, frozenset[str]]
type Inputs = Mapping[str, str | int | bool]
type SubkeyRef = Mapping[str, str]
type Key = str | SubkeyRef
type AttrsValidator[T] = Callable[[AttrsInstance, Attribute[Any], T], None]

type Freezer[FV] = Callable[[Mapping[str, object]], FrozenDict[str, FV]]
type MappingConverter[FV] = Callable[[Mapping[str, object]], FrozenDict[str, FV]]
type TypeConverter[T, FV] = Callable[[T], FrozenDict[str, FV]]
type OptionalMappingConverter[FV] = Callable[
    [Mapping[str, object] | None], FrozenDict[str, FV]
]
type OptionalTypeConverter[T, FV] = Callable[[T | None], FrozenDict[str, FV]]
type DefFunc[T, R] = Callable[[T | None], R]

_KEY_QUALIFIERS = frozenset({"Required", "NotRequired"})

# Args
type BasicMapping = Mapping[str, BasicValue]
type BasicArg = BasicValue | BasicMapping | Sequence[BasicValue]
type DataclassLike = DataclassInstance | type[DataclassInstance]

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


# Other
@runtime_checkable
class TypeRequire[T, R](Protocol):
    def __call__(self, value: T, what: str | None = None, **_: Any) -> R: ...  # noqa: E704


@runtime_checkable
class InstanceRequire[T, R](Protocol):
    def __call__(  # noqa: E704
        self, cls: type[R], value: T, what: str | None = None, **_: Any
    ) -> R: ...


type Require[T, R] = TypeRequire[T, R] | InstanceRequire[T, R]


def _is_classvar(annotation: object) -> bool:
    if isinstance(annotation, str):
        text = annotation.strip()
        result = text == "ClassVar" or text.startswith(("ClassVar[", "typing.ClassVar"))
    else:
        result = annotation is ClassVar or get_origin(annotation) is ClassVar

    return result


def _keep_or_has_value(*keep_fields: str):
    keep = frozenset(keep_fields)

    def has_value(field: Field[Any] | Attribute[Any], value: object) -> bool:
        if isinstance(value, (Mapping, tuple)):
            _has_value = bool(value)
        else:
            _has_value = value is not None

        return _has_value or field.name in keep

    return has_value


@overload
def _freeze_value(  # noqa: E704
    value: object, json_native: Literal[True]
) -> FrozenJSON: ...
@overload
def _freeze_value(value: object, json_native: bool = ...) -> object: ...  # noqa: E704
def _freeze_value(value: object, json_native: bool = False) -> object:  # noqa: E302
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
    elif isinstance(value, (list, tuple)):
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
    items = (data if is_mapping(data) else dict(data)).items()
    check = partial(require_str, what="mapping key") if json_native else None
    keyed = ((key if check is None else check(key), item) for key, item in items)
    return {key: _freeze_value(item, json_native) for key, item in keyed}


@overload
def narrow_from_require[T, R](  # noqa: E704
    require: InstanceRequire[T, R], cls: type[R], /, **kwargs: object
) -> Callable[[R], R]: ...
@overload  # noqa: E302
def narrow_from_require[T, R](  # noqa: E704
    require: Require[object, R], *args: object, accepted: TypeForm[T], **kwargs: object
) -> Callable[[T], R]: ...
@overload  # noqa: E302
def narrow_from_require[T, R](  # noqa: E704
    require: Require[T, R], *args: object, **kwargs: object
) -> Callable[[R], R]: ...
def narrow_from_require[T, R](  # noqa: E302
    require: Require[T, R], *args: object, accepted: object = None, **kwargs: object
) -> Callable[..., R]:
    """
    Advertises a typed converter to callers but validates any object at runtime.

    The advertised input is the guard's output type, or ``accepted`` when given.
    ``accepted`` only sets that static type. ``args`` and ``kwargs`` are bound as
    ``functools.partial`` does. A class bound before the value (as ``require_instance``
    takes it) also sets the advertised type.

    Args:

        require: The guard to run on each value.
        args: Arguments bound before the value, such as ``require_instance``'s class.

    Kwargs:

        accepted: The input type to advertise in place of the guard's output type.
        **kwargs: Keyword arguments bound to ``require``, such as ``what``.

    Returns:

        A one-argument converter that returns the guard's result.

    Examples:

        >>> narrow_from_require(require_str, what="name")("abc")
        'abc'
        >>> narrow_from_require(require_instance, int, what="count")(3)
        3
        >>> to_binding = narrow_from_require(require_binding, accepted=str)
        >>> to_binding("db")
        FrozenDict({'db': 'db'})

    """
    return partial(require, *args, **kwargs)


def _get_key_qualifier(annotation: object) -> str | None:
    """Gets the outermost ``Required``/``NotRequired`` of a string annotation."""
    source = getattr(annotation, "__forward_arg__", annotation)
    node = ast.parse(source, mode="eval").body if isinstance(source, str) else None
    head = node.value if isinstance(node, ast.Subscript) else None

    if isinstance(head, ast.Name):
        name = head.id
    elif isinstance(head, ast.Attribute):
        name = head.attr
    else:
        name = None

    return name if name in _KEY_QUALIFIERS else None


def _require_typed_dict_class(item: TypeForm[object]) -> type:
    """Narrows ``item`` to a TypedDict class or raises ``TypeError``."""
    if not (is_typeddict(item) and isinstance(item, type)):
        raise TypeError(f"{item!r} is not a TypedDict")

    return item


def typed_dict_keys[T](item: TypeForm[T]) -> tuple[frozenset[str], frozenset[str]]:
    """Obtains the semantic required and optional keys of a TypedDict."""
    cls = _require_typed_dict_class(item)
    required = set(cls.__required_keys__)
    optional = set(cls.__optional_keys__)

    for key, annotation in cls.__annotations__.items():
        qualifier = _get_key_qualifier(annotation)

        if qualifier == "Required":
            required.add(key)
            optional.discard(key)
        elif qualifier == "NotRequired":
            optional.add(key)
            required.discard(key)

    return frozenset(required), frozenset(optional)


def require_from_typed_dict[T](
    item: TypeForm[T],
    what: str | None = None,
    *,
    exclude: Collection[str] = (),
    extra: Collection[str] = (),
    error: type[Exception] = InvalidPipelineError,
) -> TypeRequire[Mapping[str, object], T]:
    cls = _require_typed_dict_class(item)
    _required, _optional = typed_dict_keys(cls)
    default_what = cls.__name__ if what is None else what
    excluded = frozenset(exclude)
    required = _required - excluded
    allowed = ((_required | _optional) - excluded).union(extra)

    def require(value: Mapping[str, object], what: str | None = None, **_) -> T:
        """Confirms a mapping has only the TypedDict's keys and all required ones."""
        what = default_what if what is None else what
        keys = set(value)

        if unknown := keys - allowed:
            raise error(f"unknown {what} key(s): {sorted(unknown)}")
        elif missing := required - keys:
            raise error(f"missing {what} key(s): {sorted(missing)}")

        return cls(**value)

    return require


def required_attrs_keys(cls: type[AttrsInstance]) -> frozenset[str]:
    """
    Names the ``__init__`` arguments of an attrs ``cls`` that have no default.

    Args:

        cls: An attrs-decorated type.

    Returns:

        The required argument names, using each field's init alias.

    Examples:

        >>> @attrs.define
        ... class Point:
        ...     x: int
        ...     _label: str = attrs.field(alias="label")
        ...     y: int = 0
        >>>
        >>> sorted(required_attrs_keys(Point))
        ['label', 'x']

    """
    fields = attrs.fields(cls)
    is_required = lambda field: field.init and field.default is attrs.NOTHING
    return frozenset(field.alias for field in fields if is_required(field))


def require_from_attrs[T: AttrsInstance, V](
    cls: type[T],
    what: str | None = None,
    *,
    exclude: Collection[str] = (),
    extra: Collection[str] = (),
    error: type[Exception] = InvalidPipelineError,
) -> TypeRequire[Mapping[str, V], dict[str, V]]:
    default_what = cls.__name__ if what is None else what
    required = required_attrs_keys(cls) - frozenset(exclude)
    allowed = field_names(cls).union(extra)

    def require(value: Mapping[str, V], what: str | None = None, **_) -> dict[str, V]:
        """Confirms a mapping has only the attrs' keys and all required ones."""
        what = default_what if what is None else what
        keys = set(value)

        if unknown := keys - allowed:
            raise error(f"unknown {what} key(s): {sorted(unknown)}")
        elif missing := required - keys:
            raise error(f"missing {what} key(s): {sorted(missing)}")

        return dict(value)

    return require


@overload
def def_from_require[T, R](  # noqa: E704
    require: TypeRequire[T, R],
    *,
    default: None = ...,
    what: str | None = ...,
    **kwargs: Any,
) -> DefFunc[T, R | None]: ...
@overload  # noqa: E302
def def_from_require[T, D, R](  # noqa: E704
    require: TypeRequire[T, R], *, default: D, what: str | None = ..., **kwargs: Any
) -> DefFunc[T, R | D]: ...
@overload  # noqa: E302
def def_from_require[T, R](  # noqa: E704
    require: InstanceRequire[T, R],
    cls: type[R],
    /,
    *,
    default: None = ...,
    what: str | None = ...,
    **kwargs: Any,
) -> DefFunc[T, R | None]: ...
@overload  # noqa: E302
def def_from_require[T, D, R](  # noqa: E704
    require: InstanceRequire[T, R],
    cls: type[R],
    /,
    *,
    default: D,
    what: str | None = ...,
    **kwargs: Any,
) -> DefFunc[T, R | D]: ...
def def_from_require[D, R](  # noqa: E302
    require: Callable[..., R],
    *args: object,
    default: D | None = None,
    what: str | None = None,
    **kwargs: Any,
) -> Callable[..., R | D | None]:
    """
    Adapts a ``require_*`` guard into an attrs converter that ignores ``None``s.

    A ``None`` value becomes ``default``. Anything else is checked with
    ``require(*args, value, **kwargs)``. ``args`` are bound before the value (just like
    ``functools.partial``). ``what`` is forwarded only when given.

    Args:

        require: The guard to run on a non-``None`` value.
        args: Arguments bound before the value, such as ``require_instance``'s class.

    Kwargs:

        default: The result for ``None``.
        what: The name used in the guard's error messages.
        **kwargs: Other keyword arguments bound to ``require``, such as ``error``.

    Returns:

        A one-argument attrs converter.

    Examples:

        >>> from riko.types._guards import require_mapping
        >>>
        >>> optional_mapping = def_from_require(require_mapping, error=TypeError)
        >>> optional_mapping(None) is None
        True
        >>> optional_mapping("abc")
        Traceback (most recent call last):
        ...
        TypeError: value must be a mapping
        >>> optional_count = def_from_require(require_instance, int, default=0)
        >>> optional_count(None), optional_count(3)
        (0, 3)

    """
    extra = kwargs if what is None else {**kwargs, "what": what}

    def optional(value: object) -> R | D | None:
        return default if value is None else require(*args, value, **extra)

    return optional


def def_from_typed_dict[T, D](
    item: TypeForm[T],
    default: D | None = None,
    what: str | None = None,
    exclude: Collection[str] = (),
    extra: Collection[str] = (),
) -> DefFunc[Mapping[str, object], T | D | None]:
    require = require_from_typed_dict(item, what, exclude=exclude, extra=extra)
    return def_from_require(require, default=default, what=what)


@overload
def narrow_def_from_require[R](  # noqa: E704
    require: TypeRequire[R, R], default: None = ...
) -> DefFunc[R, R | None]: ...
@overload  # noqa: E302
def narrow_def_from_require[D, R](  # noqa: E704
    require: TypeRequire[R, R], default: D
) -> DefFunc[R, R | D]: ...
@overload  # noqa: E302
def narrow_def_from_require[R](  # noqa: E704
    require: TypeRequire[R, R], default: None = ..., what: str | None = ...
) -> DefFunc[R, R | None]: ...
@overload  # noqa: E302
def narrow_def_from_require[D, R](  # noqa: E704
    require: TypeRequire[R, R], default: D, what: str | None = ...
) -> DefFunc[R, R | D]: ...
@overload  # noqa: E302
def narrow_def_from_require[T, R](  # noqa: E704
    require: TypeRequire[object, R],
    default: None = ...,
    what: str | None = ...,
    *,
    accepted: TypeForm[T],
) -> DefFunc[T, R | None]: ...
@overload  # noqa: E302
def narrow_def_from_require[T, D, R](  # noqa: E704
    require: TypeRequire[object, R],
    default: D,
    what: str | None = ...,
    *,
    accepted: TypeForm[T],
) -> DefFunc[T, R | D]: ...
def narrow_def_from_require[D, R](  # noqa: E302
    require: TypeRequire[Any, R],
    default: D | None = None,
    what: str | None = None,
    *,
    accepted: object = None,
) -> Callable[..., R | D | None]:
    """
    Adapts a ``require_*`` guard to a typed attrs converter that ignores ``None``s.

    A ``None`` value becomes ``default``. Anything else is checked with ``require``.
    The advertised input is the guard's output type, or ``accepted`` when given.
    ``accepted`` only sets that static type.

    Args:

        require: The guard to run on a value that isn't ``None``.
        default: The result for ``None``.
        what: The name used in the guard's error messages.

    Kwargs:

        accepted: The input type to advertise in place of the guard's output type.

    Returns:

        A one-argument attrs converter.

    Examples:

        >>> to_binding = narrow_def_from_require(require_binding, {}, accepted=str)
        >>> to_binding(None)
        {}
        >>> to_binding("db")
        FrozenDict({'db': 'db'})

    """

    def optional(value: object) -> R | D | None:
        kwargs = {} if what is None else {"what": what}
        return default if value is None else require(value, **kwargs)

    return optional


def validator_from_require(
    require: Callable[..., object],
    *args: object,
    optional: bool = False,
    **kwargs: object,
) -> AttrsValidator[object]:
    """
    Adapts a ``require_*`` guard into an attrs field validator.

    The validator calls ``require(*args, value, label, **kwargs)``, so ``args`` are
    bound before the value as with ``functools.partial``. The label names the
    class and field.

    Args:

        require: The guard to run on the field's value.
        args: Positional arguments passed before the value.
        optional: Whether ``None`` skips the check.
        kwargs: Keyword arguments passed to ``require``.

    Returns:

        An attrs validator.

    Examples:

        >>> is_bool = validator_from_require(require_instance, bool, error=TypeError)
        >>>
        >>> @attrs.define
        ... class Settings:
        ...     ordered: bool = attrs.field(validator=is_bool)
        >>>
        >>> Settings(ordered=1)
        Traceback (most recent call last):
        ...
        TypeError: Settings 'ordered' must be of type bool, not int

    """

    def validator(
        instance: AttrsInstance, field: Attribute[Any], value: object
    ) -> None:
        label = f"{type(instance).__name__} '{field.name}'"
        require(*args, value, label, **kwargs)

    return validators.optional(validator) if optional else validator


def validator_from_typed_dict[T](
    item: TypeForm[T],
    what: str | None = None,
    optional: bool = False,
    exclude: Collection[str] = (),
    extra: Collection[str] = (),
):
    require = require_from_typed_dict(item, what, exclude=exclude, extra=extra)
    return validator_from_require(require, optional=optional)


def require_instance[T](
    cls: type[T],
    value: object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> T:
    """
    Narrows ``value`` to an instance of ``cls`` or raises ``error`` otherwise.

    Examples:

        >>> require_instance(str, "a")
        'a'
        >>> require_instance(str, 1)
        Traceback (most recent call last):
        ...
        riko.base.exceptions.InvalidPipelineError: ...value must be of type str, not int

    """
    if not isinstance(value, cls):
        msg = f"{what} must be of type {cls.__name__}, not {type(value).__name__}"
        raise error(msg)

    return value


@overload
def require_instances[K, T](  # noqa: E704
    cls: type[T],
    value: Mapping[K, object],
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> dict[K, T]: ...
@overload  # noqa: E302
def require_instances[T](  # noqa: E704
    cls: type[T],
    value: Iterable[object],
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Iterable[T]: ...
def require_instances[K, T](  # noqa: E302
    cls: type[T],
    value: Mapping[K, object] | Iterable[object],
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> dict[K, T] | Iterable[T]:
    """
    Narrows every value of a mapping or iterable to an instance of ``cls``.

    Args:

        cls: The class every value must be an instance of.
        value: The mapping or iterable to check.
        what: The name used in error messages.

    Kwargs:

        error: The exception raised for a value that isn't a ``cls``.

    Returns:

        A new dict for a mapping, else a list, of the checked values.

    Raises:

        error: If any value isn't an instance of ``cls``. Names the offending key or
            position so a caller can tell which entry failed.

    Examples:

        >>> require_instances(int, {"a": 1})
        {'a': 1}
        >>> require_instances(int, {"a": 1, "b": "x"}, "count", error=TypeError)
        Traceback (most recent call last):
        ...
        TypeError: count 'b' must be of type int, not str

    """
    require = partial(require_instance, cls, error=error)

    if is_mapping(value):
        items = value.items()
        result = {k: require(v, f"{what} {k!r}") for k, v in items}
    else:
        items = enumerate(value)
        result = [require(v, f"{what} position {k!r}") for k, v in items]

    return result


require_str = partial(require_instance, str)


def instances_freezer[T](
    cls: type[T], what: str, *, error: type[Exception] = InvalidPipelineError
) -> Freezer[T]:
    """
    Builds a freezer that requires every value of a mapping to be a ``cls`` instance.

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
def mapping_converter[FV](  # noqa: E704
    freezer: Freezer[FV], *, what: str = ..., error: type[Exception] = ...
) -> MappingConverter[FV]: ...
@overload  # noqa: E302
def mapping_converter[FV, T](  # noqa: E704
    freezer: Freezer[FV],
    accepted: TypeForm[T],
    /,
    *,
    what: str = ...,
    error: type[Exception] = ...,
) -> TypeConverter[T, FV]: ...
def mapping_converter[FV](  # noqa: E302
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
def optional_mapping_converter[FV](  # noqa: E704
    freezer: Freezer[FV],
    *,
    default: Mapping[str, object] | None = ...,
    what: str = ...,
    error: type[Exception] = ...,
) -> OptionalMappingConverter[FV]: ...
@overload  # noqa: E302
def optional_mapping_converter[FV, T](  # noqa: E704
    freezer: Freezer[FV],
    accepted: TypeForm[T],
    /,
    *,
    default: Mapping[str, object] | None = ...,
    what: str = ...,
    error: type[Exception] = ...,
) -> OptionalTypeConverter[T, FV]: ...
def optional_mapping_converter[FV](  # noqa: E302
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

        >>> converter = optional_mapping_converter(freeze_json)
        >>> converter(None)
        FrozenDict({})
        >>> converter = optional_mapping_converter(freeze_json, default={"a": 1})
        >>> converter(None)
        FrozenDict({'a': 1})
        >>> converter({"b": 2})
        FrozenDict({'b': 2})

    """
    item: Mapping[str, object] = {} if default is None else default

    def converter(value: object) -> FrozenDict[str, FV]:
        mapped = item if value is None else require_mapping(value, what, error=error)
        return freezer(mapped)

    return converter


def require_strlike(
    value: object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> str | tuple[str, ...]:
    """
    Narrows ``value`` to a ``str`` or a tuple of strs.

    Args:

        value: The value to check.
        what: The name used in the error message.

    Kwargs:

        error: The exception raised when ``value`` is neither.

    Returns:

        ``value`` for a ``str``, else a tuple of its items.

    Raises:

        error: If ``value`` is neither a ``str`` nor an iterable of strs.

    Examples:

        >>> require_strlike("id"), require_strlike(iter(["a", "b"]))
        ('id', ('a', 'b'))
        >>> require_strlike(["a", 1], "keys")
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...keys must be a str or iterable...

    """
    if isinstance(value, str):
        valid = True
    elif isinstance(value, Iterable):
        value = tuple(value)
        valid = all(isinstance(v, str) for v in value)
    else:
        valid = False

    if not valid:
        raise error(f"{what} must be a str or iterable of strs")

    return cast("str | tuple[str, ...]", value)


def normalize_strs(
    value: StrLike | None,
    what: str = "keys",
    *,
    strict: bool = False,
    type_error: type[Exception] = InvalidPipelineError,
    value_error: type[Exception] = InvalidPipelineError,
) -> tuple[str, ...]:
    """
    Normalizes ``value`` into a tuple of keys.

    A bare string is wrapped and each item of an iterable must be a non-empty string.

    Args:

        value: One key, an iterable of keys, or ``None``.
        what: How to name the keys in an error.
        strict: Whether ``None`` is rejected rather than read as no keys.
        type_error: The error raised when ``value`` is not a string or iterable.
        value_error: The error raised for an empty, non-string, or duplicate key.

    Returns:

        The keys as a tuple, empty when ``value`` is ``None`` and not ``strict``.

    Raises:

        InvalidPipelineError: When ``value`` is not a string or iterable of
            strings (including ``None`` when ``strict``), or a key is empty, not a
            string, or a duplicate, unless ``type_error``/``value_error`` name other
            errors.

    Examples:

        >>> normalize_strs("id")
        ('id',)
        >>> normalize_strs(["a", "b"])
        ('a', 'b')
        >>> normalize_strs(None)
        ()
        >>> normalize_strs(None, "names", strict=True)
        Traceback (most recent call last):
        ...
        riko.base.exceptions.InvalidPipelineError: ...names must be a string or...

    """
    if value is None and not strict:
        keys: tuple[str, ...] = ()
    elif value is None or not isinstance(value, Iterable):
        raise type_error(f"{what} must be a string or iterable of strings")
    else:
        keys = (value,) if isinstance(value, str) else tuple(value)

        if not all(key and isinstance(key, str) for key in keys):
            raise value_error(f"{what} must be non-empty strings")
        elif len(set(keys)) != len(keys):
            raise value_error(f"duplicate {what} are not allowed: {keys!r}")

    return keys


def require_finite(
    value: float,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> float:
    """
    Narrows ``value`` to a finite float.

    Raises ``error`` when ``value`` is NaN or infinite.
    """
    if isnan(value) or isinf(value):
        msg = f"{what} must be a finite float to be JSON-native, got {value!r}"
        raise error(msg)

    return value


def require_binding(
    value: object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> FrozenDict[str, str]:
    """
    Narrows ``value`` to a resource binding (map of local alias to Context name).

    A bare name, or each name of an iterable, is bound to itself.

    Args:

        value: A name, an iterable of names, or a mapping of alias to name.
        what: The name used in error messages.

    Kwargs:

        error: The exception raised for a malformed binding.

    Returns:

        The binding as a ``FrozenDict`` that maps local alias to Context name.

    Raises:

        error: If ``value`` has the wrong shape, an alias or name isn't a non-empty
            string, or an alias repeats.

    Examples:

        >>> require_binding(["db", "cache"])
        FrozenDict({'db': 'db', 'cache': 'cache'})
        >>> require_binding({"db": "primary_db"})
        FrozenDict({'db': 'primary_db'})

    """
    if isinstance(value, str):
        pairs = [(value, value)]
    elif isinstance(value, Mapping):
        pairs = list(value.items())
    elif isinstance(value, Iterable):
        pairs = [(name, name) for name in value]
    else:
        raise error(f"{what} must be a str, mapping, or iterable of strs")

    if not all(isinstance(name, str) and name for pair in pairs for name in pair):
        raise error(f"{what} must bind non-empty strings, got {value!r}")
    elif len(dict(pairs)) < len(pairs):
        raise error(f"{what} must not repeat an alias, got {value!r}")

    return FrozenDict(cast("list[tuple[str, str]]", pairs))


def serialize_dataclass(
    value: DataclassLike, *keep_fields: str, compact: bool = True
) -> dict[str, object]:
    """
    Reads a dataclass's set fields into a dict.

    A field that is ``None`` or an empty mapping or tuple is left out unless it is
    named in ``keep_fields``.

    Args:

        value: The dataclass instance or class to read.
        keep_fields: Names of fields to include even when they are unset.
        compact: Whether to leave out unset fields; when false, every field is kept.

    Returns:

        The field names mapped to their values.

    Examples:

        >>> from dataclasses import dataclass
        >>>
        >>> @dataclass
        ... class Rule:
        ...     field: str
        ...     default: str | None = None
        >>>
        >>> serialize_dataclass(Rule("title"))
        {'field': 'title'}

    """
    filterer = _keep_or_has_value(*keep_fields) if compact else lambda *_: True
    pairs = ((field, getattr(value, field.name)) for field in fields(value))
    return {field.name: item for field, item in pairs if filterer(field, item)}


def serialize_attrs(
    value: AttrsInstance, *keep_fields: str, recurse: bool = False, compact: bool = True
) -> dict[str, object]:
    """
    Reads an attrs record's set fields into a dict.

    A field that is ``None`` or an empty mapping or tuple is left out unless it is
    named in ``keep_fields``. A mapping field, including a ``FrozenDict``, is kept as
    is.

    Args:

        value: The attrs record to read.
        keep_fields: Names of fields to include even when they are unset.
        recurse: Whether a field holding another attrs record is read into a dict too.
        compact: Whether to leave out unset fields; when false, every field is kept.

    Returns:

        The field names mapped to their values.

    Examples:

        >>> @attrs.define
        ... class Point:
        ...     x: int
        ...     label: str | None = None
        >>>
        >>> @attrs.define
        ... class Segment:
        ...     start: Point
        ...     end: Point
        >>>
        >>> serialize_attrs(Point(1))
        {'x': 1}
        >>> serialize_attrs(Point(1), "label")
        {'x': 1, 'label': None}
        >>> serialize_attrs(Segment(Point(0), Point(1)), recurse=True)
        {'start': {'x': 0}, 'end': {'x': 1}}

    """
    filterer = _keep_or_has_value(*keep_fields)
    asdict = partial(attrs.asdict, filter=filterer) if compact else attrs.asdict
    result = asdict(value, recurse=False)
    serialize = partial(serialize_attrs, recurse=True, compact=compact)
    unwrap = lambda item: serialize(item) if is_attrs_inst(item) else item
    return map_values(unwrap, result) if recurse else result


@final
@attrs.define(frozen=True, slots=True, eq=False, repr=False, init=False)
class FrozenDict[K, V](Mapping[K, V]):
    """
    A read-only mapping whose built-in container values are frozen too.

    It copies its source, a mapping or key/value pairs, and freezes the values as
    ``freeze`` does, so it never changes once built. It compares equal to any
    mapping with the same items.

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
        object.__setattr__(self, "_data", dict(frozen))  # noqa: PLC2801

    def __getitem__(self, key: K) -> V:
        return self._data[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({dict(self._data)!r})"

    @classmethod
    def from_frozen(cls, data: Mapping[K, V]) -> FrozenDict[K, V]:
        """Wraps ``data`` whose values the caller has already frozen."""
        frozen = object.__new__(cls)
        object.__setattr__(frozen, "_data", dict(data))  # noqa: PLC2801
        return frozen


@overload
def freeze(value: None) -> None: ...  # noqa: E704
@overload  # noqa: E302
def freeze[K, V](  # noqa: E704
    value: Mapping[K, list[V]],
) -> FrozenDict[K, tuple[V]]: ...
@overload  # noqa: E302
def freeze[K, V](  # noqa: E704
    value: Mapping[K, set[V]],
) -> FrozenDict[K, frozenset[V]]: ...
@overload  # noqa: E302
def freeze[K, V](value: Mapping[K, V]) -> FrozenDict[K, V]: ...  # noqa: E704
@overload  # noqa: E302
def freeze[T](value: list[T] | tuple[T, ...]) -> tuple[T, ...]: ...  # noqa: E704
@overload  # noqa: E302
def freeze[T](value: set[T] | frozenset[T]) -> frozenset[T]: ...  # noqa: E704
@overload  # noqa: E302
def freeze[T](value: T) -> T: ...  # noqa: E704
def freeze(value: object) -> object:  # noqa: E302
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

        >>> frozen = freeze({"a": [1, {"b": {2}}], "c": object})
        >>> frozen["a"]
        (1, FrozenDict({'b': frozenset({2})}))
        >>> frozen["c"]
        <class 'object'>

    """
    return _freeze_value(value)


@overload
def freeze_json(value: None) -> None: ...  # noqa: E704
@overload  # noqa: E302
def freeze_json(  # noqa: E704
    value: Mapping[str, object],
) -> FrozenDict[str, FrozenJSON]: ...
@overload  # noqa: E302
def freeze_json(  # noqa: E704
    value: Mapping[object, object],
) -> FrozenDict[str, FrozenJSON]: ...
@overload  # noqa: E302
def freeze_json(value: object) -> FrozenJSON: ...  # noqa: E704
def freeze_json(value: object) -> FrozenJSON:  # noqa: E302
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
def thaw[K, V](value: Mapping[K, V]) -> dict[K, V]: ...  # noqa: E704
@overload  # noqa: E302
def thaw(value: object) -> object: ...  # noqa: E704
def thaw(value: object) -> object:  # noqa: E302
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
