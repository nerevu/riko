# vim: sw=4:ts=4:expandtab
"""
riko.modules._metadata
~~~~~~~~~~~~~~~~~~~~~~~
Module type/subtype derivation and the derived module catalog. Metadata is
inferred from each pipe's implementation contract (return kind, ftype) rather
than declared, and the catalog is discovered from the package at runtime.
"""

import builtins
from collections.abc import Iterator
from functools import partial
from importlib import import_module
from pkgutil import iter_modules as iter_package_modules
from typing import Literal, overload
from typing import cast as cast_type

from riko.cast import BasicCastType
from riko.modules._inference import _gen_operator_return_kinds
from riko.types.general import ModuleWrapper, Pipeline
from riko.types.modules import (
    ModuleMetadata,
    ModuleSubtype,
    ModuleSubtypes,
    ModuleType,
    OperatorReturnKind,
)
from riko.utils import broadcast

_PACKAGE = "riko.modules"

SUBTYPES: dict[ModuleSubtype, ModuleType] = {
    "source": "processor",
    "transformer": "processor",
    "splitter": "splitter",
    "composer": "operator",
    "aggregator": "operator",
}


def _derive_operator_subtypes(
    pipe: Pipeline,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    subtype: ModuleSubtype | None = None
    subtypes: ModuleSubtypes = set()

    for kind in _gen_operator_return_kinds(pipe):
        if kind == OperatorReturnKind.NONSTREAM:
            subtype = subtype or "aggregator"
            subtypes.add(subtype)
        elif kind == OperatorReturnKind.STREAM:
            subtype = subtype or "composer"
            subtypes.add("composer")

        if subtype and subtypes == {"aggregator", "composer"}:
            break

    if not subtypes:
        qualified_name = f"{pipe.__module__}.{pipe.__name__}"
        msg = f"{qualified_name} no supported subtypes found"
        raise TypeError(msg)

    return subtype, subtypes


def _derive_loopable(name: str, module_type: ModuleType) -> bool:
    return module_type == "processor" and name != "input"


def _derive_subtypes(
    pipe: Pipeline, module_type: ModuleType, **kwargs
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    if module_type == "processor":
        none_ftype = kwargs.get("ftype") == BasicCastType.NONE
        subtype: ModuleSubtype | None = "source" if none_ftype else "transformer"
        result = subtype, cast_type(ModuleSubtypes, {subtype})
    elif module_type == "splitter":
        result = "splitter", cast_type(ModuleSubtypes, {"splitter"})
    else:
        result = _derive_operator_subtypes(pipe)

    return result


def _get_module_metadata(name: str) -> ModuleMetadata | None:
    module = import_module(f"{_PACKAGE}.{name}")
    pipes = (getattr(module, target, None) for target in ("pipe", "async_pipe"))
    targets = tuple(cast_type(ModuleWrapper, pipe) for pipe in pipes if callable(pipe))
    attrs = ("name", "type", "subtype", "subtypes", "pollable", "loopable")

    if len(targets) == 2:
        for attr in attrs:
            actual = getattr(targets[0], attr)
            expected = getattr(targets[1], attr)

            if actual != expected:
                msg = f"{module.__name__} has inconsistent sync/async metadata: "
                msg += f"{expected!r} != {actual!r}"
                raise TypeError(msg)

    if targets:
        first = targets[0]

        if first.name != name:
            raise TypeError(f"{module.__name__} reports module name {first.name!r}")

        for subtype in first.subtypes:
            expected_type = SUBTYPES[subtype]

            if first.type != expected_type:
                msg = f"{module.__name__} supports subtype {subtype!r}, "
                msg += f"which requires type {expected_type!r}, not {first.type!r}"
                raise TypeError(msg)

        metadata = ModuleMetadata(
            name=name,
            type=first.type,
            subtype=first.subtype,
            subtypes=first.subtypes,
            pollable=any(t.pollable for t in targets),
            loopable=any(t.loopable for t in targets),
            has_sync=any(not t.isasync for t in targets),
            has_async=any(t.isasync for t in targets),
        )
    else:
        metadata = None

    return metadata


def gen_module_catalog() -> Iterator[ModuleMetadata]:
    package = import_module(_PACKAGE)

    for info in iter_package_modules(package.__path__):
        skip = info.ispkg or info.name.startswith("_")

        if not skip and (metadata := _get_module_metadata(info.name)):
            yield metadata


def _matches_subtype(
    module: ModuleMetadata, subtype: ModuleSubtype | None, *, primary: bool
) -> bool:
    if subtype is None:
        matched = True
    elif primary:
        matched = module.subtype == subtype
    else:
        matched = subtype in module.subtypes

    return matched


@overload
def list_modules(  # noqa: E704
    *,
    type: ModuleType | None = ...,  # noqa: A002
    subtype: ModuleSubtype | None = ...,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[False] = ...,
) -> tuple[str, ...]: ...
@overload  # noqa: E302
def list_modules(  # noqa: E704
    *,
    type: ModuleType | None = None,  # noqa: A002
    subtype: ModuleSubtype | None = None,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[True],
) -> tuple[ModuleMetadata, ...]: ...
def list_modules(  # noqa: E302
    *,
    type: ModuleType | None = None,  # noqa: A002
    subtype: ModuleSubtype | None = None,
    primary: bool = False,
    loopable: bool | None = None,
    show_metadata: bool = False,
) -> tuple[str, ...] | tuple[ModuleMetadata, ...]:
    if type and subtype:
        raise ValueError("type and subtype cannot be combined")
    elif primary and not subtype:
        raise ValueError("primary=True requires subtype")

    subtype_match = partial(_matches_subtype, subtype=subtype, primary=primary)
    type_match = lambda module: type is None or module.type == type
    loop_match = lambda module: loopable is None or module.loopable is loopable
    match = lambda module: all(broadcast(module, subtype_match, type_match, loop_match))
    # dynamic filter pipe import shadows the builtin filter
    filtered = builtins.filter(match, gen_module_catalog())
    modules = tuple(sorted(filtered, key=lambda module: module.name))
    return modules if show_metadata else tuple(module.name for module in modules)
