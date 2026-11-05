"""
The ``require_*`` narrowing guards and their attrs adapters.

Each guard narrows a value or raises, and the ``narrow_*``/``def_from_*``/
``validator_from_*`` helpers turn a guard into an attrs converter or validator. It also
reads a TypedDict's required and optional keys, normalizes key lists, and raises on a
pipe call's missing required argument or conf key.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Collection, Iterable, Mapping
from functools import partial
from math import isinf, isnan
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    cast,
    get_args,
    get_origin,
    is_typeddict,
    overload,
    runtime_checkable,
)

from attrs import Attribute, AttrsInstance, validators
from typing_extensions import TypeForm

from ._exceptions import InvalidPipelineError
from ._guards import is_mapping, require_mapping
from ._iterutils import gen_instances, sort_stably
from ._recordutils import field_names, required_attrs_keys
from ._typing import gen_union_members

if TYPE_CHECKING:
    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types._enums import StrLike

type AttrsValidator[T] = Callable[[AttrsInstance, Attribute[Any], T], None]
type DefFunc[T, R] = Callable[[T | None], R]
type Require[T, R] = TypeRequire[T, R] | InstanceRequire[T, R]

_KEY_QUALIFIERS = frozenset({"Required", "NotRequired"})


@runtime_checkable
class TypeRequire[T, R](Protocol):
    """
    A guard that narrows a value to ``R``.

    ``what`` names the value in error messages. The ``*_from_require`` helpers turn
    any such guard into an attrs converter or validator.
    """

    def __call__(self, value: T, what: str | None = None) -> R: ...


@runtime_checkable
class InstanceRequire[T, R](Protocol):
    """
    A guard that narrows a value to ``cls``, as ``require_instance`` does.

    The helpers that accept it apply the class first, which also types their result
    for that class.
    """

    def __call__(self, cls: type[R], value: T, what: str | None = None) -> R: ...


@overload
def narrow_from_require[T, R](
    require: InstanceRequire[T, R], cls: type[R], /, **kwargs: object
) -> Callable[[R], R]: ...
@overload
def narrow_from_require[T, R](
    require: Require[object, R], *args: object, accepted: TypeForm[T], **kwargs: object
) -> Callable[[T], R]: ...
@overload
def narrow_from_require[T, R](
    require: Require[T, R], *args: object, **kwargs: object
) -> Callable[[R], R]: ...
def narrow_from_require[T, R](
    require: Require[T, R], *args: object, accepted: object = None, **kwargs: object
) -> Callable[..., R]:
    """
    Advertises a typed converter to callers but validates any object at runtime.

    The advertised input is the guard's output type, or ``accepted`` when given.
    ``accepted`` only sets that static type. ``args`` and ``kwargs`` are applied as
    ``functools.partial`` does. A class applied before the value (as
    ``require_instance`` takes it) also sets the advertised type.

    Args:

        require: The guard to run on each value.
        args: Arguments applied before the value, such as ``require_instance``'s class.

    Kwargs:

        accepted: The input type to advertise in place of the guard's output type.
        **kwargs: Keyword arguments applied to ``require``, such as ``what``.

    Returns:

        A one-argument converter that returns the guard's result.

    Examples:

        >>> narrow_from_require(require_str, what="name")("abc")
        'abc'
        >>> narrow_from_require(require_instance, int, what="count")(3)
        3
        >>> to_keys = narrow_from_require(normalize_strs, accepted=str)
        >>> to_keys("db")
        ('db',)

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
    """
    Gets a TypedDict's required and optional keys.

    A ``Required``/``NotRequired`` qualifier wins over the class's totality, even in a
    string annotation that was never evaluated, which ``__required_keys__`` alone
    can miss.

    Args:

        item: The TypedDict to inspect.

    Returns:

        The required keys, then the optional keys.

    Raises:

        TypeError: If ``item`` is not a TypedDict class.

    Examples:

        >>> from typing import NotRequired, TypedDict
        >>>
        >>> class Embed(TypedDict):
        ...     name: str
        ...     id: NotRequired[str]
        >>>
        >>> required, optional = typed_dict_keys(Embed)
        >>> sorted(required), sorted(optional)
        (['name'], ['id'])

    """
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


def require_from_keys[V](
    required: Collection[str],
    allowed: Collection[str],
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
) -> TypeRequire[Mapping[str, V], dict[str, V]]:
    """
    Builds a guard that requires a mapping's keys to fit explicit key sets.

    Use ``require_from_typed_dict`` or ``require_from_attrs`` instead when the keys
    come from a TypedDict or an attrs class respectively since they derive the key sets.

    Args:

        required: The keys that must be present.
        allowed: The keys that may be present (every required key is allowed).
        what: The name used in error messages.

    Kwargs:

        error: The exception raised for an unknown or missing key.

    Returns:

        A guard that returns a copy of the mapping.

    Examples:

        >>> require_point = require_from_keys({"x"}, {"y"}, "point")
        >>> require_point({"x": 1, "y": 2})
        {'x': 1, 'y': 2}
        >>> require_point({"y": 2})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...missing point key(s): ['x']
        >>> require_point({"x": 1, "z": 3})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...unknown point key(s): ['z']

    """
    _required = frozenset(required)
    _allowed = _required.union(allowed)
    default_what = what

    def require(value: Mapping[str, V], what: str | None = None, **_) -> dict[str, V]:
        """Confirms a mapping has only the allowed keys and all required ones."""
        what = default_what if what is None else what
        keys = set(value)

        if unknown := keys - _allowed:
            raise error(f"unknown {what} key(s): {sorted(unknown)}")
        elif missing := _required - keys:
            raise error(f"missing {what} key(s): {sorted(missing)}")

        return dict(value)

    return require


def require_from_typed_dict[T](
    item: TypeForm[T],
    what: str | None = None,
    *,
    exclude: Collection[str] = (),
    not_required: Collection[str] = (),
    extra: Collection[str] = (),
    error: type[Exception] = InvalidPipelineError,
) -> TypeRequire[Mapping[str, object], T]:
    """
    Builds a guard that requires a mapping's keys to fit a TypedDict.

    Equivalent to ``require_from_form`` if you don't need ``exclude``, ``not_required``,
    or ``extra``. Use ``require_from_form`` instead if you need to check against
    a tuple of TypedDicts.

    Args:

        item: The TypedDict whose keys the mapping must fit.
        what: The name used in error messages (default: the TypedDict's name).

    Kwargs:

        exclude: Keys of ``item`` the mapping must not have.
        not_required: Required keys of ``item`` the mapping may leave out.
        extra: Keys outside ``item`` the mapping may also have.
        error: The exception raised for an unknown or missing key.

    Returns:

        A guard that returns the mapping as a new ``item``.

    Raises:

        TypeError: If ``item`` is not a TypedDict class.

    Examples:

        >>> from typing import TypedDict
        >>>
        >>> class Point(TypedDict):
        ...     x: int
        ...     y: int
        >>>
        >>> require_from_typed_dict(Point, not_required={"y"})({"x": 1})
        {'x': 1}
        >>> require_from_typed_dict(Point, exclude={"y"})({"x": 1, "y": 2})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...unknown Point key(s): ['y']

    """
    cls = _require_typed_dict_class(item)
    _required, _optional = typed_dict_keys(cls)
    required = _required.difference(exclude, not_required)
    allowed = (_required | _optional).difference(exclude).union(extra)
    default_what = cls.__name__ if what is None else what
    check = require_from_keys(required, allowed, default_what, error=error)

    def require(value: Mapping[str, object], what: str | None = None, **_) -> T:
        """Confirms a mapping has only the TypedDict's keys and all required ones."""
        return cls(**check(value, what))

    return require


def require_from_attrs[T: AttrsInstance, V](
    cls: type[T],
    what: str | None = None,
    *,
    exclude: Collection[str] = (),
    not_required: Collection[str] = (),
    extra: Collection[str] = (),
    error: type[Exception] = InvalidPipelineError,
) -> TypeRequire[Mapping[str, V], dict[str, V]]:
    """
    Builds a guard that requires a mapping's keys to fit an attrs ``__init__``.

    Use ``require_instance`` instead to check a ``cls`` instance. This guard checks a
    mapping meant to build one.

    Args:

        cls: The attrs class whose ``__init__`` arguments the mapping must fit.
        what: The name used in error messages (default: the class name).

    Kwargs:

        exclude: Arguments of ``cls`` the mapping must not have.
        not_required: Required arguments of ``cls`` the mapping may leave out.
        extra: Keys outside ``cls`` the mapping may also have.
        error: The exception raised for an unknown or missing key.

    Returns:

        A guard that returns a copy of the mapping.

    Examples:

        >>> import attrs
        >>>
        >>> @attrs.define
        ... class Point:
        ...     x: int
        ...     y: int
        >>>
        >>> require_from_attrs(Point, not_required={"y"})({"x": 1})
        {'x': 1}
        >>> require_from_attrs(Point, not_required={"y"})({"y": 2})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...missing Point key(s): ['x']
        >>> require_from_attrs(Point, exclude={"y"})({"x": 1, "y": 2})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...unknown Point key(s): ['y']

    """
    excluded = frozenset(exclude)
    required = required_attrs_keys(cls) - excluded - frozenset(not_required)
    allowed = (field_names(cls) - excluded).union(extra)
    default_what = cls.__name__ if what is None else what
    return require_from_keys(required, allowed, default_what, error=error)


@overload
def def_from_require[T, R](
    require: TypeRequire[T, R],
    *,
    default: None = ...,
    what: str | None = ...,
    **kwargs: object,
) -> DefFunc[T, R | None]: ...
@overload
def def_from_require[T, D, R](
    require: TypeRequire[T, R], *, default: D, what: str | None = ..., **kwargs: object
) -> DefFunc[T, R | D]: ...
@overload
def def_from_require[T, R](
    require: InstanceRequire[T, R],
    cls: type[R],
    /,
    *,
    default: None = ...,
    what: str | None = ...,
    **kwargs: object,
) -> DefFunc[T, R | None]: ...
@overload
def def_from_require[T, D, R](
    require: InstanceRequire[T, R],
    cls: type[R],
    /,
    *,
    default: D,
    what: str | None = ...,
    **kwargs: object,
) -> DefFunc[T, R | D]: ...
def def_from_require[D, R](
    require: Callable[..., R],
    *args: object,
    default: D | None = None,
    what: str | None = None,
    **kwargs: object,
) -> Callable[..., R | D | None]:
    """
    Adapts a ``require_*`` guard into an attrs converter that ignores ``None``s.

    A ``None`` value becomes ``default``. Anything else is checked with
    ``require(*args, value, **kwargs)``. ``args`` are applied before the value
    (just like ``functools.partial``). ``what`` is forwarded only when given.

    Args:

        require: The guard to run on a non-``None`` value.
        args: Arguments applied before the value, such as ``require_instance``'s class.

    Kwargs:

        default: The result for ``None``.
        what: The name used in the guard's error messages.
        **kwargs: Other keyword arguments applied to ``require``, such as ``error``.

    Returns:

        A one-argument attrs converter.

    Examples:

        >>> from riko.base._guards import require_mapping
        >>>
        >>> optional_mapping = def_from_require(require_mapping, error=TypeError)
        >>> optional_mapping(None)
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
    *,
    not_required: Collection[str] = (),
) -> DefFunc[Mapping[str, object], T | D | None]:
    """
    Adapts a TypedDict to an attrs converter that ignores ``None``s.

    A ``None`` value becomes ``default``. Anything else is checked against the
    TypedDict.

    Args:

        item: The TypedDict whose keys the mapping must fit.
        default: The result for ``None``.
        what: The name used in error messages (default: the TypedDict's name).
        exclude: Keys of ``item`` the mapping must not have.
        extra: Keys outside ``item`` the mapping may also have.

    Kwargs:

        not_required: Required keys of ``item`` the mapping may leave out.

    Returns:

        A one-argument converter.

    Examples:

        >>> from typing import TypedDict
        >>>
        >>> class Point(TypedDict):
        ...     x: int
        >>>
        >>> to_point = def_from_typed_dict(Point, default={"x": 0})
        >>> to_point(None), to_point({"x": 1})
        ({'x': 0}, {'x': 1})

    """
    require = require_from_typed_dict(
        item, what, exclude=exclude, not_required=not_required, extra=extra
    )
    return def_from_require(require, default=default, what=what)


@overload
def narrow_def_from_require[R](
    require: TypeRequire[R, R], default: None = ...
) -> DefFunc[R, R | None]: ...
@overload
def narrow_def_from_require[D, R](
    require: TypeRequire[R, R], default: D
) -> DefFunc[R, R | D]: ...
@overload
def narrow_def_from_require[R](
    require: TypeRequire[R, R], default: None = ..., what: str | None = ...
) -> DefFunc[R, R | None]: ...
@overload
def narrow_def_from_require[D, R](
    require: TypeRequire[R, R], default: D, what: str | None = ...
) -> DefFunc[R, R | D]: ...
@overload
def narrow_def_from_require[T, R](
    require: TypeRequire[object, R],
    default: None = ...,
    what: str | None = ...,
    *,
    accepted: TypeForm[T],
) -> DefFunc[T, R | None]: ...
@overload
def narrow_def_from_require[T, D, R](
    require: TypeRequire[object, R],
    default: D,
    what: str | None = ...,
    *,
    accepted: TypeForm[T],
) -> DefFunc[T, R | D]: ...
def narrow_def_from_require[T, D, R](
    require: TypeRequire[T, R],
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

        >>> to_keys = narrow_def_from_require(normalize_strs, (), accepted=str)
        >>> to_keys(None)
        ()
        >>> to_keys("db")
        ('db',)

    """

    def optional(value: T | None) -> R | D | None:
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
    applied before the value as with ``functools.partial``. The label names the
    class and field.

    Args:

        require: The guard to run on the field's value.
        args: Positional arguments passed before the value.
        optional: Whether ``None`` skips the check.
        kwargs: Keyword arguments passed to ``require``.

    Returns:

        An attrs validator.

    Examples:

        >>> import attrs
        >>>
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
        instance: AttrsInstance, field: Attribute[object], value: object
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
    *,
    not_required: Collection[str] = (),
) -> AttrsValidator[object]:
    """
    Builds an attrs validator that checks a mapping's keys against a TypedDict.

    Args:

        item: The TypedDict whose keys the mapping must fit.
        what: The name used in error messages (default: the TypedDict's name).
        optional: Whether ``None`` skips the check.
        exclude: Keys of ``item`` the mapping must not have.
        extra: Keys outside ``item`` the mapping may also have.

    Kwargs:

        not_required: Required keys of ``item`` the mapping may leave out.

    Returns:

        An attrs validator.

    Examples:

        >>> import attrs
        >>>
        >>> from typing import TypedDict
        >>>
        >>> class Point(TypedDict):
        ...     x: int
        >>>
        >>> @attrs.define
        ... class Shape:
        ...     origin: dict = attrs.field(validator=validator_from_typed_dict(Point))
        >>>
        >>> Shape({"x": 1}).origin
        {'x': 1}
        >>> Shape({"y": 1})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...unknown Shape 'origin' key(s)...

    """
    require = require_from_typed_dict(
        item, what, exclude=exclude, not_required=not_required, extra=extra
    )
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
    Narrows ``value`` to an instance of ``cls``, or raises ``error`` otherwise.

    Use ``require_from_form`` instead to pass an alias or union of classes. Combine with
    ``validator_from_require`` or ``def_from_require`` to build an attrs validator or
    converter for one class.

    Args:

        cls: The class ``value`` must be an instance of.
        value: The value to check.
        what: The name used in the error message.

    Kwargs:

        error: The exception raised when ``value`` isn't a ``cls``.

    Returns:

        ``value``, typed as ``cls``.

    Raises:

        error: If ``value`` isn't an instance of ``cls``.

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
def require_instances[K, T](
    cls: type[T],
    value: Mapping[K, object],
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> dict[K, T]: ...
@overload
def require_instances[T](
    cls: type[T],
    value: Iterable[object],
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> Iterable[T]: ...
def require_instances[K, T](
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


def require_nonblank_str(
    value: object,
    what: str | None = "value",
    *,
    error: type[Exception] = InvalidPipelineError,
    **_,
) -> str:
    """
    Narrows ``value`` to a string with at least one non-whitespace character.

    Args:

        value: The value to check.
        what: The name used in the error message.

    Kwargs:

        error: The exception raised when ``value`` isn't such a string.

    Returns:

        ``value``, typed as ``str``.

    Raises:

        error: If ``value`` isn't a string, or is empty or only whitespace.

    Examples:

        >>> require_nonblank_str(" a ", "node 'id'")
        ' a '
        >>> require_nonblank_str(" ", "node 'id'")
        Traceback (most recent call last):
        ...
        riko.base.exceptions.InvalidPipelineError: ...node 'id' must not be blank

    """
    text = require_str(value, what, error=error)

    if not text.strip():
        raise error(f"{what} must not be blank")

    return text


def require_from_form[T](
    form: TypeForm[T],
    what: str | None = None,
    *,
    error: type[Exception] = InvalidPipelineError,
) -> TypeRequire[object, T]:
    """
    Builds a guard that narrows a value to a type.

    Use it when all you have is the type, such as a union or an alias of one:

    - An alias is checked as the type it names.
    - A lone class is checked with ``require_instance``.
    - A lone TypedDict is checked with ``require_from_typed_dict``, so unknown and
      missing keys raise.
    - A ``Literal`` is checked by value and type, so ``Literal[1]`` rejects ``True``
      even though ``True == 1``.
    - A union is checked against each member, and any mapping matches a TypedDict
      member no matter its keys.

    Use ``require_instance`` instead to build a validator or converter for one class,
    e.g., ``validator_from_require(require_instance, bool)``. Use
    ``require_from_typed_dict`` instead when you need ``exclude``, ``not_required``,
    or ``extra``.

    Args:

        form: The type the guard narrows to.
        what: The name used in error messages (default: the name of ``form``).

    Kwargs:

        error: The exception raised for a value that doesn't fit.

    Returns:

        A guard that returns the value typed as ``form``.

    Raises:

        TypeError: If ``form`` contains anything other than classes, TypedDicts, and
            ``Literal`` types.

    Examples:

        >>> from typing import Literal, TypedDict
        >>>
        >>> class Point(TypedDict):
        ...     x: int
        >>>
        >>> type Coord = Point | int | str
        >>> require_from_form(Point)({"y": 1})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...unknown Point key(s): ['y']
        >>> require_coord = require_from_form(Coord, error=TypeError)
        >>> require_coord({"y": 1})
        {'y': 1}
        >>> require_coord(1.5)
        Traceback (most recent call last):
            ...
        TypeError: Coord must be of type int | str | mapping, not float
        >>> require_from_form(Literal["a", "b"], "mode")("c")
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...mode: 'c'. Expected one of a, b

    """
    default_what = getattr(form, "__name__", "value") if what is None else what
    leaves = tuple(gen_union_members(form))
    classes = tuple(gen_instances(leaves, type))
    shapes = tuple(cls for cls in classes if not is_typeddict(cls))
    arms = tuple(leaf for leaf in leaves if get_origin(leaf) is Literal)
    literals = tuple(arg for arm in arms for arg in get_args(arm))

    def is_member(value: object) -> bool:
        return any(type(value) is type(arg) and value == arg for arg in literals)

    if _unsupported := set(leaves).difference(classes, arms):
        unsupported = ", ".join(map(repr, sort_stably(_unsupported)))

        if len(_unsupported) > 1:
            raise TypeError(f"{unsupported} are not classes, TypedDicts, or Literals")
        else:
            raise TypeError(f"{unsupported} is not a class, TypedDict, or Literal")
    elif not classes:
        accepted = ", ".join(map(str, literals))

        def check(value: object, what: str) -> object:
            if not is_member(value):
                raise error(f"Invalid {what}: {value!r}. Expected one of {accepted}")

            return value

    elif len(classes) == 1 and not (shapes or literals):
        typed = require_from_typed_dict(classes[0], default_what, error=error)

        def check(value: object, what: str) -> object:
            return typed(require_mapping(value, what, error=error), what)

    elif len(classes) == 1 and not literals:
        check = partial(require_instance, classes[0], error=error)
    else:
        is_mappable = len(shapes) < len(classes)
        names = [cls.__name__ for cls in shapes] + (["mapping"] if is_mappable else [])
        names += [repr(arg) for arg in literals]
        expected = f"of type {' | '.join(names)}" if shapes or literals else "a mapping"

        def check(value: object, what: str) -> object:
            member_or_shape = is_member(value) or isinstance(value, shapes)

            if not (member_or_shape or (is_mappable and is_mapping(value))):
                raise error(f"{what} must be {expected}, not {type(value).__name__}")

            return value

    def require(value: object, what: str | None = None, **_) -> T:
        """Narrows ``value`` to ``form``."""
        return cast("T", check(value, default_what if what is None else what))

    return require


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
        result: str | tuple[str, ...] | None = value
    elif isinstance(value, Iterable):
        items = tuple(value)
        strs = tuple(gen_instances(items, str))
        result = strs if len(strs) == len(items) else None
    else:
        result = None

    if result is None:
        raise error(f"{what} must be a str or iterable of strs")

    return result


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

    Rejects NaN and infinity, which JSON cannot carry.

    Args:

        value: The float to check.
        what: The name used in the error message.

    Kwargs:

        error: The exception raised for NaN or infinity.

    Returns:

        ``value``.

    Raises:

        error: If ``value`` is NaN or infinite.

    Examples:

        >>> require_finite(1.5)
        1.5
        >>> require_finite(float("inf"), "rate")
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...rate must be a finite float...

    """
    if isnan(value) or isinf(value):
        msg = f"{what} must be a finite float to be JSON-native, got {value!r}"
        raise error(msg)

    return value


def require_arg[T](value: T | None, name: str, module: str, strict: bool = False) -> T:
    """
    Narrows a module's required keyword argument to ``T`` and raises when it is omitted.

    The argument is one that a module's ``pipe`` passes on to its ``parser`` function,
    which declares it keyword-only as ``T | None = None``. Omitting it raises this
    error. The error names the module and the argument.

    Args:

        value: The supplied argument value, or ``None`` when omitted.

        name: The argument being validated, used in the error message.

        module: The module name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. an empty
            ``others`` list that would publish to nobody. Use it only where a
            falsy value can never be legitimate — never on an argument for
            which ``0``, ``False`` or ``""`` is a real value (default: False).

    Returns:

        The value, narrowed to ``T``.

    Raises:

        TypeError: If ``value`` is ``None``, or is falsy under ``strict``.

    Examples:

        >>> require_arg(len, "func", "udf")
        <built-in function len>
        >>> require_arg(None, "func", "udf")
        Traceback (most recent call last):
            ...
        TypeError: the 'udf' module requires the 'func' keyword argument

        >>> # A falsy value passes unless strict is set
        >>> require_arg([], "others", "send")
        []
        >>> require_arg([], "others", "send", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'send' module requires the 'others' keyword argument

    """
    if (value is None) or (strict and not value):
        raise TypeError(f"the {module!r} module requires the {name!r} keyword argument")

    return value


def require_conf_key[T](
    objconf: DynamicConf, key: str, module: str, strict: bool = False
) -> T:  # pyright: ignore[reportInvalidTypeVarUse]
    """
    Reads a module's required conf key and raises when the conf leaves it unset.

    Only the conf is checked. A field missing from an item is a data condition
    the module skips, not an error.

    Args:

        objconf: The parsed module configuration.

        key: The conf key that must be set.

        module: The module name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. a ``url``
            set to ``""``. Use it only where a falsy value can never be
            legitimate — never on a key for which ``0``, ``False`` or ``""`` is
            a real value (default: False).

    Returns:

        The value stored under ``key``.

    Raises:

        TypeError: If ``key`` is absent or ``None``, or is falsy under
            ``strict``.

    Examples:

        >>> from meza.fntools import Objectify
        >>>
        >>> require_conf_key(Objectify({"url": "x"}), "url", "csv")
        'x'
        >>> require_conf_key(Objectify({}), "url", "csv")
        Traceback (most recent call last):
            ...
        TypeError: the 'csv' module requires the 'url' conf key

        >>> # A falsy value passes unless strict is set
        >>> require_conf_key(Objectify({"url": ""}), "url", "csv")
        ''
        >>> require_conf_key(Objectify({"url": ""}), "url", "csv", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'csv' module requires the 'url' conf key

    """
    value = getattr(objconf, key, None)

    if (value is None) or (strict and not value):
        raise TypeError(f"the {module!r} module requires the {key!r} conf key")

    return cast("T", value)
