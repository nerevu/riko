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

from riko._importutils import import_or_else
from riko._iterutils import broadcast
from riko.ext.names import derive_category, normalize_module_name
from riko.ext.registry import ModuleDefinition, registry
from riko.types._names import ModuleNameLike
from riko.types._wrappers import ModuleWrapper
from riko.types.modules import ModuleCategory, ModuleMetadata, ModuleSubtype, ModuleType

_PACKAGE = "riko.modules"

SUBTYPES: dict[ModuleSubtype, ModuleType] = {
    "source": "processor",
    "transformer": "processor",
    "splitter": "splitter",
    "composer": "operator",
    "aggregator": "operator",
}


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


def get_module_metadata(name: ModuleNameLike) -> ModuleMetadata | None:
    canonical = normalize_module_name(name)
    module = import_module(f"{_PACKAGE}.{canonical}")
    pipes = (getattr(module, target, None) for target in ("pipe", "async_pipe"))
    targets = tuple(cast(ModuleWrapper, pipe) for pipe in pipes if callable(pipe))
    label = module.__name__
    return _metadata_from_targets(canonical, targets, label=label, strict_naming=True)


def gen_module_catalog(name: str | None = None) -> Iterator[ModuleMetadata]:
    package = import_module(_PACKAGE)

    for info in iter_package_modules(package.__path__):
        skip = info.ispkg or info.name.startswith("_")

        if not skip and (metadata := get_module_metadata(info.name)):
            yield metadata


def gen_registry_catalog() -> Iterator[ModuleMetadata]:
    """
    Metadata for runtime-registered + entry-point modules (the extension
    surface). Deriving it forces each entry-point extension to import. Listing
    the catalog is an explicit "show everything" operation. A definition whose
    callables carry no module metadata (e.g. a bare lambda) is skipped.
    """
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
    category: ModuleCategory | str | None = ...,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[False] = ...,
) -> list[str]: ...
@overload  # noqa: E302
def list_modules(  # noqa: E704
    *,
    type: ModuleType | str | None = None,  # noqa: A002
    subtype: ModuleSubtype | str | None = None,
    category: ModuleCategory | str | None = ...,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[True],
) -> list[ModuleMetadata]: ...
def list_modules(  # noqa: E302
    *,
    type: ModuleType | str | None = None,  # noqa: A002
    subtype: ModuleSubtype | str | None = None,
    category: ModuleCategory | str | None = None,
    primary: bool = False,
    loopable: bool | None = None,
    show_metadata: bool = False,
) -> list[str] | list[ModuleMetadata]:
    if type and subtype:
        raise ValueError("type and subtype cannot be combined")
    elif primary and not subtype:
        raise ValueError("primary=True requires subtype")

    subtype_match = partial(_matches_subtype, subtype=subtype, primary=primary)
    type_match = lambda module: type is None or module.type == type
    loop_match = lambda module: loopable is None or module.loopable is loopable
    user_match = lambda module: category is None or derive_category(module) == category
    matches = subtype_match, type_match, loop_match, user_match
    match = lambda module: all(broadcast(module, *matches))

    # built-ins first, then registry (runtime + entry-point) modules shadow them
    catalog = {metadata.name: metadata for metadata in gen_module_catalog()}
    catalog.update((metadata.name, metadata) for metadata in gen_registry_catalog())

    # dynamic filter pipe import shadows the builtin filter
    filtered = builtins.filter(match, catalog.values())
    modules = sorted(filtered, key=lambda module: module.name)
    return modules if show_metadata else [module.name for module in modules]


def _gen_doc(module: object) -> Iterator[str]:
    lines = (getattr(module, "__doc__", "") or "").strip().splitlines()
    return map(str.strip, lines)


def describe_module(name: ModuleNameLike | None) -> ModuleDefinition | None:
    """
    Returns a module's definition, or None when the name is unknown.

    A built-in is described from its module rather than the registry, so its
    ``description`` comes from the docstring summary and its pipe callables are
    read off the module. A registry definition instead reports whatever its
    registrant supplied, which may leave the callables unset; ``get_pipe``
    resolves either.

    Args:
        name: The module name, either a str or a discovery-tree member.

    Returns:
        The definition, or None when no module answers to ``name``.

    Examples:
        >>> from riko import Sources
        >>>
        >>> fetch = describe_module(Sources.FETCH)
        >>> fetch.name
        'fetch'
        >>> fetch.description
        'Fetches an RSS feed and yields feed entries.'
        >>> fetch.sync_pipe.__name__, fetch.async_pipe.__name__
        ('pipe', 'async_pipe')
        >>> fetch.get_pipe("pipe") is fetch.sync_pipe
        True
        >>> describe_module("does-not-exist")

    """
    if canonical := normalize_module_name(name):
        if (definition := registry.definition(canonical)) is None:  # noqa: SIM102
            if module := import_or_else(f"{_PACKAGE}.{canonical}"):
                definition = ModuleDefinition(
                    name=canonical,
                    module=module,
                    sync_pipe=getattr(module, "pipe", None),
                    async_pipe=getattr(module, "async_pipe", None),
                    description=next(_gen_doc(module), None),
                )
    else:
        definition = None

    return definition
