from __future__ import annotations

import re
import sys
from dataclasses import fields, is_dataclass
from types import UnionType
from typing import TYPE_CHECKING, Literal, Union, get_args, get_origin, get_type_hints

import riko.types._enums as names_module
import riko.types._scalars as scalars_module
from riko.types._collections import RikoValue, StringyDict, StringyList
from riko.types._enums import ModuleName
from riko.types._guards import is_mapping
from riko.types.modules import RegexConfRule, RegexRule

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.types._enums import ModuleNameLike

    from ._dynamic_conf import DynamicConf


def fromdict(
    cls: type[DataclassInstance],
    **data: DataclassInstance | RikoValue | StringyList | StringyDict,
) -> DataclassInstance:
    """
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
    localns = {**callerns, **vars(module), **vars(names_module), **vars(scalars_module)}
    hints = get_type_hints(cls, localns=localns, include_extras=True)

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


def make_regex_rule(
    f: str, m: str, r: str, seriesmatch: bool = True, default: str | None = None
) -> RegexConfRule:
    return RegexConfRule(
        field=f, match=m, replace=r, seriesmatch=seriesmatch, default=default
    )


def get_regex_rule(
    rule: DynamicConf | RegexConfRule, recompile: bool = False
) -> RegexRule:
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


def normalize_module_name(name: ModuleNameLike | None) -> str:
    """Normalizes a module name to its canonical string."""
    return name.value if isinstance(name, ModuleName) else name or ""
