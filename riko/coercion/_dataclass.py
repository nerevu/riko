"""Dataclass and rule coercion helpers used by module configuration."""

from __future__ import annotations

import re
import sys
from collections import ChainMap
from dataclasses import fields, is_dataclass
from types import UnionType
from typing import TYPE_CHECKING, Literal, Union, get_args, get_origin

import riko.types._enums as enums_module
import riko.types._scalars as scalars_module
from riko.base._guards import is_mapping
from riko.base._require_guards import require_from_form
from riko.base._typing import resolve_type_hints
from riko.types.modules import RegexConfRule, RegexRule

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.types._values import RikoDict, RikoValue

    from ._dynamic_conf import DynamicConf


def fromdict(
    cls: type[DataclassInstance], **data: DataclassInstance | RikoValue | RikoDict
) -> DataclassInstance:
    """
    Builds a dataclass while coercing nested mappings into nested dataclasses.

    Optional dataclass fields are resolved recursively. Union fields with multiple
    non-``None`` alternatives are left unchanged because their target type is
    ambiguous.

    Args:

        cls: Dataclass type to construct.

    Kwargs:

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

    """
    # Adds the caller's namespace so dataclasses defined in a local scope (e.g. a
    # doctest or test body) resolve PEP 563 string (from __future__ import annotations)
    # annotations
    module = sys.modules[cls.__module__]
    caller = sys._getframe(1)
    callerns = ChainMap(caller.f_locals, caller.f_globals)
    namespaces = (callerns, module, enums_module, scalars_module)
    hints = resolve_type_hints(cls, *namespaces, include_extras=True)

    for f in fields(cls):
        if f.name not in data:
            continue

        ftype = hints[f.name]
        val = data[f.name]
        origin = get_origin(ftype)

        if origin is Union or origin is UnionType:
            non_null = [a for a in get_args(ftype) if a is not type(None)]

            if len(non_null) == 1:
                ftype = non_null[0]
                origin = get_origin(ftype)

        if origin is Literal:
            require_from_form(ftype, f.name, error=ValueError)(val)
        elif is_dataclass(ftype) and isinstance(ftype, type) and is_mapping(val):
            val = fromdict(ftype, **val)

        data[f.name] = val

    return cls(**data)


def build_regex_conf_rule(
    f: str, m: str, r: str, seriesmatch: bool = True, nativereplace: bool = False
) -> RegexConfRule:
    """
    Builds a parsed regex configuration rule from compact arguments.

    Args:

        f: Item field to operate on.
        m: Regular-expression pattern to match.
        r: Replacement text.

    Kwargs:

        seriesmatch: Whether later rules operate on the previous rule's result.

        nativereplace: Whether ``r`` uses Python's ``re`` syntax rather than ``$N``
            group references.

    Returns:

        A ``RegexConfRule`` containing the supplied values and standard defaults.

    Examples:

        >>> rule = build_regex_conf_rule("title", "foo", "bar")
        >>> rule.field, rule.match, rule.replace, rule.seriesmatch
        ('title', 'foo', 'bar', True)

    """
    return RegexConfRule(
        field=f,
        match=m,
        replace=r,
        seriesmatch=seriesmatch,
        nativereplace=nativereplace,
    )


def build_regex_rule(rule: DynamicConf | RegexConfRule) -> RegexRule:
    r"""
    Builds an executable rule mapping from a parsed regex configuration.

    Compiles the match expression and translates ``$N`` replacement references to
    Python's ``\N``. A rule with ``nativereplace`` set keeps its replacement as written,
    in Python's ``re`` syntax.

    Args:

        rule: Parsed dynamic or dataclass regex rule.

    Returns:

        A normalized ``RegexRule`` used by regex processing modules.

    Raises:

        TypeError: If a mapping ``rule`` has a ``default``, which belongs on the module
            configuration, keyed by field.

    Examples:

        >>> args = ("title", r"(\w+) shipping")
        >>> item = {"title": "Express shipping"}
        >>>
        >>> dollar_rule = build_regex_conf_rule(*args, "$1 delivery")
        >>> rule = build_regex_rule(dollar_rule)
        >>> rule["replace"]
        '\\1 delivery'
        >>> rule["match"].sub(rule["replace"], item[rule["field"]])
        'Express delivery'
        >>>
        >>> # A literal "$5" needs nativereplace. Otherwise it reads as group 5
        >>> native_rule = build_regex_conf_rule(*args, r"\1: $5", nativereplace=True)
        >>> rule = build_regex_rule(native_rule)
        >>> rule["replace"]
        '\\1: $5'
        >>> rule["match"].sub(rule["replace"], item[rule["field"]])
        'Express: $5'

    """
    if not is_dataclass(rule):
        if "default" in rule:
            msg = "a regex rule has no 'default'; set conf['default'][<field>] instead"
            raise TypeError(msg)

        keys = {f.name for f in fields(RegexConfRule)}
        filtered = {k: v for k, v in rule.items() if k in keys}
        rule = RegexConfRule(**filtered)

    flags = 0 if rule.casematch else re.IGNORECASE

    if not rule.singlelinematch:
        flags |= re.MULTILINE
        flags |= re.DOTALL

    count: int = 1 if rule.singlelinematch else 0

    if rule.nativereplace:
        replace = rule.replace
    else:
        replace = re.sub(r"\$(\d+)", r"\\\1", rule.replace)

    nrule = {
        "count": count,
        "flags": flags,
        "match": re.compile(rule.match, flags),
        "replace": replace,
        "field": rule.field,
        "series": rule.seriesmatch,
    }

    return RegexRule(**nrule)
