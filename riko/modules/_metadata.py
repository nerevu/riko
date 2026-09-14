# vim: sw=4:ts=4:expandtab
"""
riko.modules._metadata
~~~~~~~~~~~~~~~~~~~~~~~
Module type/subtype derivation and the derived module catalog. Metadata is
inferred from each pipe's implementation contract (return kind, ftype) rather
than declared, and the catalog is discovered from the package at runtime.
"""

from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module
from pkgutil import iter_modules as iter_package_modules
from typing import TYPE_CHECKING, Literal, cast, overload

from riko.base._imports import import_or_else
from riko.coercion._dataclass import normalize_module_name
from riko.definitions.modules import ModuleDefinition
from riko.runtime._registry import registry
from riko.types._wrappers import ModuleWrapper
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

if TYPE_CHECKING:
    from riko.types._enums import ModuleNameLike

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


@overload
def get_module_metadata(  # noqa: E704
    name: ModuleNameLike, strict: Literal[False] = ...
) -> ModuleMetadata | None: ...
@overload  # noqa: E302
def get_module_metadata(  # noqa: E704
    name: ModuleNameLike, strict: Literal[True]
) -> ModuleMetadata: ...
def get_module_metadata(  # noqa: E302
    name: ModuleNameLike, strict: bool = False
) -> ModuleMetadata | None:
    canonical = normalize_module_name(name)
    module = import_module(f"{_PACKAGE}.{canonical}")
    pipes = (getattr(module, target, None) for target in ("pipe", "async_pipe"))
    targets = tuple(cast(ModuleWrapper, pipe) for pipe in pipes if callable(pipe))
    label = module.__name__
    metadata = _metadata_from_targets(
        canonical, targets, label=label, strict_naming=True
    )

    if strict and metadata is None:
        raise ValueError(f"Module {name!r} has no metadata")

    return metadata


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
    is_async = (True, False)

    for name in registry.catalog_names():
        definition = registry.definition(name)
        pipes = map(definition.get_pipe, is_async) if definition else ()
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


def _gen_doc(module: object) -> Iterator[str]:
    lines = (getattr(module, "__doc__", "") or "").strip().splitlines()
    return map(str.strip, lines)


def describe_module(name: ModuleNameLike | None) -> ModuleDefinition | None:
    """
    Describes a module, or reports None when the name is unknown.

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
        >>> fetch.get_pipe() is fetch.sync_pipe
        True
        >>> describe_module("does-not-exist")

    """
    if canonical := normalize_module_name(name):
        definition: ModuleDefinition | None = registry.definition(canonical)

        if definition is None:  # noqa: SIM102
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
