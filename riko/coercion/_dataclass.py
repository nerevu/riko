"""Dataclass and rule coercion helpers used by module configuration."""

from __future__ import annotations

import re
import sys
from dataclasses import fields, is_dataclass
from types import UnionType
from typing import TYPE_CHECKING, Literal, Union, get_args, get_origin

import riko.types._enums as names_module
import riko.types._scalars as scalars_module
from riko.base._typing import resolve_type_hints
from riko.types._guards import is_mapping
from riko.types.modules import RegexConfRule, RegexRule

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.types._collections import RikoValue, StringyDict, StringyList

    from ._dynamic_conf import DynamicConf


def fromdict(
    cls: type[DataclassInstance],
    **data: DataclassInstance | RikoValue | StringyList | StringyDict,
) -> DataclassInstance:
    """
    Builds a dataclass while coercing nested mappings into nested dataclasses.

    Optional dataclass fields are resolved recursively. Union fields with multiple
    non-``None`` alternatives are left unchanged because their target type is
    ambiguous.

    Args:

        cls: Dataclass type to construct.
        **data: Field values used to construct ``cls``.

    Returns:

        A new ``cls`` instance with unambiguous nested dataclasses coerced.

    Raises:

        TypeError: When ``cls`` is not a dataclass type.
        ValueError: When a ``Literal`` field receives a value outside its choices.

    Examples:

        >>> from dataclasses import dataclass
        >>>
        >>> @dataclass
        ... class Inner:
        ...     n: int = 0
        >>> @dataclass
        ... class Outer:
        ...     inner: Inner | None = None
        >>> fromdict(Outer, inner={'n': 5}).inner
        Inner(n=5)
        >>> @dataclass
        ... class Other:
        ...     m: int = 0
        >>> @dataclass
        ... class Either:
        ...     val: Inner | Other | None = None
        >>> fromdict(Either, val={'m': 9}).val
        {'m': 9}

    """
    # Adds the caller's namespace so dataclasses defined in a local scope (e.g. a
    # doctest or test body) resolve PEP 563 string (from __future__ import annotations)
    # annotations
    caller = sys._getframe(1)
    callerns = {**caller.f_globals, **caller.f_locals}
    module = sys.modules[cls.__module__]
    hints = resolve_type_hints(
        cls, callerns, module, names_module, scalars_module, include_extras=True
    )

    for f in fields(cls):
        if f.name not in data:
            continue

        ftype = hints[f.name]
        val = data[f.name]
        origin = get_origin(ftype)

        if origin is Union or origin is UnionType:
            non_none = [a for a in get_args(ftype) if a is not type(None)]

            if len(non_none) == 1:
                ftype = non_none[0]
                origin = get_origin(ftype)

        if origin is Literal:
            valid = get_args(ftype)

            if val not in valid:
                raise ValueError(f"Invalid {f.name}={val!r}, expected one of {valid}")
        elif is_dataclass(ftype) and isinstance(ftype, type) and is_mapping(val):
            val = fromdict(ftype, **val)

        data[f.name] = val

    return cls(**data)


def build_regex_conf_rule(
    f: str, m: str, r: str, seriesmatch: bool = True, default: str | None = None
) -> RegexConfRule:
    """
    Builds a parsed regex configuration rule from compact arguments.

    Args:

        f: Item field to operate on.
        m: Regular-expression pattern to match.
        r: Replacement text.
        seriesmatch: Whether later rules operate on the previous rule's result.
        default: Value used when the source field is missing.

    Returns:

        A ``RegexConfRule`` containing the supplied values and standard defaults.

    Examples:

        >>> rule = build_regex_conf_rule("title", "foo", "bar")
        >>> rule.field, rule.match, rule.replace, rule.seriesmatch
        ('title', 'foo', 'bar', True)

    """
    return RegexConfRule(
        field=f, match=m, replace=r, seriesmatch=seriesmatch, default=default
    )


def resolve_regex_rule(
    rule: DynamicConf | RegexConfRule, recompile: bool = False
) -> RegexRule:
    """
    Normalizes a parsed regex configuration into an executable rule mapping.

    Args:

        rule: Parsed dynamic or dataclass regex rule.
        recompile: Whether to compile the match expression and translate ``$N``
            replacement references for Python's regex engine.

    Returns:

        A normalized ``RegexRule`` used by regex processing modules.

    Examples:

        >>> rule = resolve_regex_rule(build_regex_conf_rule("title", "foo", "bar"))
        >>> rule["field"], rule["match"], rule["replace"], rule["series"]
        ('title', 'foo', 'bar', True)
        >>> conf_rule = build_regex_conf_rule("title", "foo", "bar")
        >>> compiled = resolve_regex_rule(conf_rule, True)
        >>> compiled["match"].pattern
        'foo'

    """
    if not is_dataclass(rule):
        keys = {f.name for f in fields(RegexConfRule)}
        filtered = {k: v for k, v in rule.items() if k in keys}
        rule = RegexConfRule(**filtered)

    flags = 0 if rule.casematch else re.IGNORECASE

    if not rule.singlelinematch:
        flags |= re.MULTILINE
        flags |= re.DOTALL

    count: int = 1 if rule.singlelinematch else 0

    if recompile and "$" in rule.replace:
        replace = re.sub(r"\$(\d+)", r"\\\1", rule.replace, count=0)
    else:
        replace = rule.replace

    match = re.compile(rule.match, flags) if recompile else rule.match

    nrule = {
        "count": count,
        "flags": flags,
        "match": match,
        "replace": replace,
        "default": rule.default,
        "field": rule.field,
        "offset": rule.offset or 0,
        "series": rule.seriesmatch,
    }

    return RegexRule(**nrule)
