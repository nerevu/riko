"""
Reads attrs and dataclass records.

Provides their field names, required keys, and compact field dicts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import Field, fields, is_dataclass
from functools import partial
from typing import TYPE_CHECKING, ClassVar, get_origin

import attrs
from attrs import Attribute, AttrsInstance

from ._guards import is_attrs_inst
from ._iterutils import map_values

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


type DataclassLike = DataclassInstance | type[DataclassInstance]


def _keep_or_has_value(*keep_fields: str):
    keep = frozenset(keep_fields)

    def has_value(field: Field[object] | Attribute[object], value: object) -> bool:
        if isinstance(value, (Mapping, tuple)):
            _has_value = bool(value)
        elif is_attrs_inst(value):
            _has_value = bool(serialize_attrs(value))
        else:
            _has_value = value is not None

        return _has_value or field.name in keep

    return has_value


def serialize_dataclass(
    value: DataclassLike, *keep_fields: str, compact: bool = True
) -> dict[str, object]:
    """
    Reads a dataclass's set fields into a dict.

    A field that is ``None``, an empty mapping or tuple, or an attrs record with no set
    fields is left out unless it is named in ``keep_fields``.

    Args:

        value: The dataclass instance or class to read.
        keep_fields: Names of fields to include even when they are unset.
        compact: Whether to leave out unset fields. When false, every field is kept.

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

    A field that is ``None``, an empty mapping or tuple, or an attrs record with no set
    fields is left out unless it is named in ``keep_fields``. A mapping field,
    including a ``FrozenDict``, is kept as is.

    Args:

        value: The attrs record to read.
        keep_fields: Names of fields to include even when they are unset.
        recurse: Whether a field holding another attrs record is read into a dict too.
        compact: Whether to leave out unset fields. When false, every field is kept.

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
        >>> from riko.base._recordutils import field_names
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
