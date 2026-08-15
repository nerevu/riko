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
from typing import Literal, cast, overload

from riko._iterutils import broadcast
from riko.cast import BasicCastType
from riko.modules._inference import gen_operator_return_kinds
from riko.types.general import (
    ModuleParser,
    ModuleWrapper,
)
from riko.types.modules import (
    ModuleMetadata,
    ModuleSubtype,
    ModuleSubtypes,
    ModuleType,
    OperatorReturnKind,
)

_PACKAGE = "riko.modules"

SUBTYPES: dict[ModuleSubtype, ModuleType] = {
    "source": "processor",
    "transformer": "processor",
    "splitter": "splitter",
    "composer": "operator",
    "aggregator": "operator",
}


def _derive_operator_subtypes(
    pipe: ModuleParser,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    subtype: ModuleSubtype | None = None
    subtypes: ModuleSubtypes = set()

    for kind in gen_operator_return_kinds(pipe):
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


def derive_loopable(name: str, module_type: ModuleType | str) -> bool:
    return module_type == "processor" and name != "input"


def derive_subtypes(
    pipe: ModuleParser,
    module_type: ModuleType | str,
    ftype: BasicCastType | None = None,
    **kwargs: object,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    if module_type == "processor":
        none_ftype = ftype == BasicCastType.NONE
        subtype: ModuleSubtype | None = "source" if none_ftype else "transformer"
        result = subtype, cast(ModuleSubtypes, {subtype})
    elif module_type == "splitter":
        result = "splitter", cast(ModuleSubtypes, {"splitter"})
    else:
        result = _derive_operator_subtypes(pipe)

    return result


def _metadata_from_targets(
    name: str, targets: tuple[ModuleWrapper, ...], *, label: str, strict_naming: bool
) -> ModuleMetadata | None:
    attrs = ("name", "type", "subtype", "subtypes", "pollable", "loopable")

    if len(targets) == 2:
        for attr in attrs:
            actual = getattr(targets[0], attr)
            expected = getattr(targets[1], attr)

            if actual != expected:
                msg = f"{label} has inconsistent sync/async metadata: "
                msg += f"{expected!r} != {actual!r}"
                raise TypeError(msg)

    if targets:
        first = targets[0]

        if strict_naming and first.name != name:
            raise TypeError(f"{label} reports module name {first.name!r}")

        for subtype in first.subtypes:
            expected_type = SUBTYPES[subtype]

            if first.type != expected_type:
                msg = f"{label} supports subtype {subtype!r}, "
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


def get_module_metadata(name: str) -> ModuleMetadata | None:
    module = import_module(f"{_PACKAGE}.{name}")
    pipes = (getattr(module, target, None) for target in ("pipe", "async_pipe"))
    targets = tuple(cast(ModuleWrapper, pipe) for pipe in pipes if callable(pipe))
    label = module.__name__
    return _metadata_from_targets(name, targets, label=label, strict_naming=True)


def gen_module_catalog(name: str | None = None) -> Iterator[ModuleMetadata]:
    package = import_module(_PACKAGE)

    for info in iter_package_modules(package.__path__):
        skip = info.ispkg or info.name.startswith("_")

        if not skip and (metadata := get_module_metadata(info.name)):
            yield metadata


def gen_registry_catalog() -> Iterator[ModuleMetadata]:
    """
    Metadata for runtime-registered + entry-point modules (the extension
    surface). Deriving it forces each entry-point extension to import — listing
    the catalog is an explicit "show everything" operation. A definition whose
    callables carry no module metadata (e.g. a bare lambda) is skipped.
    """
    from riko.ext.registry import registry  # noqa: PLC0415

    interfaces = ("pipe", "async_pipe")

    for name in registry.catalog_names():
        definition = registry.definition(name)
        pipes = map(definition.get_pipe, interfaces) if definition else ()
        targets = tuple(cast(ModuleWrapper, pipe) for pipe in pipes if callable(pipe))
        args = (name, targets)

        try:
            metadata = _metadata_from_targets(*args, label=name, strict_naming=False)
        except (AttributeError, TypeError):
            # a callable that isn't a metadata-carrying pipe wrapper (e.g. a
            # bare lambda) — resolvable, but not catalogable
            metadata = None

        if metadata:
            yield metadata


def _matches_subtype(
    module: ModuleMetadata, subtype: ModuleSubtype | str | None, *, primary: bool
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
    type: ModuleType | str | None = ...,  # noqa: A002
    subtype: ModuleSubtype | str | None = ...,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[False] = ...,
) -> tuple[str, ...]: ...
@overload  # noqa: E302
def list_modules(  # noqa: E704
    *,
    type: ModuleType | str | None = None,  # noqa: A002
    subtype: ModuleSubtype | str | None = None,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[True],
) -> tuple[ModuleMetadata, ...]: ...
def list_modules(  # noqa: E302
    *,
    type: ModuleType | str | None = None,  # noqa: A002
    subtype: ModuleSubtype | str | None = None,
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

    # built-ins first, then registry (runtime + entry-point) modules shadow them
    catalog = {metadata.name: metadata for metadata in gen_module_catalog()}
    catalog.update((metadata.name, metadata) for metadata in gen_registry_catalog())

    # dynamic filter pipe import shadows the builtin filter
    filtered = builtins.filter(match, catalog.values())
    modules = tuple(sorted(filtered, key=lambda module: module.name))
    return modules if show_metadata else tuple(module.name for module in modules)


def get_pipe_metadata(name: str) -> ModuleMetadata | None:
    return get_module_metadata(f"{name}")
