# vim: sw=4:ts=4:expandtab
"""
Derives, categorizes, and lists metadata for built-in and registered modules.

Examples:
    Basic usage::

        >>> from riko import get_module_metadata
        >>>
        >>> metadata = get_module_metadata("count")
        >>> metadata.name, metadata.type, metadata.subtype
        ('count', 'operator', 'aggregator')

"""

from __future__ import annotations

import builtins
from functools import partial
from importlib import import_module
from pkgutil import iter_modules as iter_package_modules
from typing import TYPE_CHECKING, Literal, overload

from riko.base._config import SINK_NAMES
from riko.base._imports import import_or_else
from riko.definitions._module_definition import ModuleDefinition, normalize_module_name
from riko.runtime._module_registry import module_registry
from riko.types._wrappers import WRAPPER_META, require_wrapper_meta
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._enums import ModuleNameLike
    from riko.types._wrappers import WrapperMeta
    from riko.types.modules import ModuleCategory

_PACKAGE = "riko.modules"

SUBTYPES: dict[ModuleSubtype, ModuleType] = {
    "source": "processor",
    "transformer": "processor",
    "splitter": "splitter",
    "composer": "operator",
    "aggregator": "operator",
}


def get_module_category(metadata: ModuleMetadata) -> ModuleCategory:
    """
    Derives the user-facing discovery category for a module.

    Categories are based on data-flow role, not the runtime module type.

    Args:

        metadata: The module's metadata.

    Returns:

        ``"source"``, ``"sink"``, or ``"transform"``.

    Examples:

        >>> from riko import get_module_metadata
        >>> from riko.ext import get_module_category
        >>>
        >>> get_module_category(get_module_metadata("fetch"))
        'source'
        >>> get_module_category(get_module_metadata("write"))
        'sink'
        >>> get_module_category(get_module_metadata("sort"))
        'transform'

    """
    if metadata.name in SINK_NAMES:
        result = "sink"
    elif metadata.subtype == "source":
        result = "source"
    else:
        result = "transform"

    return result


def _metadata_from_targets(
    name: str, targets: tuple[WrapperMeta, ...], *, label: str, strict_naming: bool
) -> ModuleMetadata | None:
    attrs = tuple(attr for attr in WRAPPER_META if attr != "isasync")

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
    """
    Derives a built-in module's metadata from its pipe callables.

    Args:

        name: Built-in module name.
        strict: Whether to raise instead of returning ``None`` when the name is not
            a built-in module or the module declares no metadata.

    Returns:

        The module's metadata, or ``None`` when ``strict`` is false and the name has
        none.

    Raises:

        ValueError: When ``strict`` is true and the name has no metadata.
        TypeError: When the module's pipe lacks module metadata, or its sync and
            async pipes disagree about their metadata.

    Examples:

        >>> get_module_metadata("count").type
        'operator'
        >>> get_module_metadata("does-not-exist") is None
        True

    """
    canonical = normalize_module_name(name)
    module = import_or_else(f"{_PACKAGE}.{canonical}") if canonical else None

    if module is None:
        metadata = None
    else:
        pipes = (getattr(module, target, None) for target in ("pipe", "async_pipe"))
        label = module.__name__
        require = partial(require_wrapper_meta, what=f"{label} pipe")
        args = (canonical, tuple(require(pipe) for pipe in pipes if callable(pipe)))
        metadata = _metadata_from_targets(*args, label=label, strict_naming=True)

    if strict and metadata is None:
        raise ValueError(f"Module {name!r} has no metadata")

    return metadata


def gen_module_catalog() -> Iterator[ModuleMetadata]:
    package = import_module(_PACKAGE)

    for info in iter_package_modules(package.__path__):
        skip = info.ispkg or info.name.startswith("_")

        if not skip and (metadata := get_module_metadata(info.name)):
            yield metadata


def gen_registry_catalog() -> Iterator[ModuleMetadata]:
    """
    Build metadata for registered and entry-point modules.

    Derivation imports each entry-point extension. Listing the catalog is an
    explicit show-everything operation. Definitions whose callables lack module
    metadata, such as bare lambdas, are skipped.
    """
    is_async = (True, False)

    for name in module_registry.catalog_names():
        definition = module_registry.load_definition(name)
        pipes = map(definition.get_pipe, is_async) if definition else ()
        targets = tuple(pipe for pipe in pipes if callable(pipe))
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
    provider: str | None = ...,
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
    provider: str | None = ...,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[True],
) -> list[ModuleMetadata]: ...
def list_modules(  # noqa: E302
    *,
    type: ModuleType | str | None = None,  # noqa: A002
    subtype: ModuleSubtype | str | None = None,
    category: ModuleCategory | str | None = None,
    provider: str | None = None,
    primary: bool = False,
    loopable: bool | None = None,
    show_metadata: bool = False,
) -> list[str] | list[ModuleMetadata]:
    """
    Lists the module names, or their metadata, that match the given filters.

    Built-in modules are listed alongside registered and entry-point modules; a
    registered module shadows a built-in of the same name.

    Kwargs:

        type: Only list modules of this module type (e.g., ``"operator"``).
        subtype: Only list modules that support this subtype (e.g., ``"aggregator"``).
        category: Only list modules in this discovery category (e.g., ``"source"``).
        provider: Only list modules from this provider (e.g., ``"riko"`` for built-ins).
        primary: Whether ``subtype`` must be marked as primary (default: False).
        loopable: List modules with matching loopability (or all modules when ``None``).
        show_metadata: Whether to list each module's metadata instead of its name.

    Returns:

        The matching module names, or their metadata when ``show_metadata`` is true,
        sorted by name.

    Raises:

        ValueError: When ``type`` and ``subtype`` are both given, or ``primary`` is true
            without a ``subtype``.

    Examples:

        >>> list_modules(subtype="aggregator", primary=True)
        ['count', 'sum']
        >>> list_modules(category="sink")
        ['write']
        >>> list_modules(provider="riko") == list_modules()
        True

    """
    if type and subtype:
        raise ValueError("type and subtype cannot be combined")
    elif primary and not subtype:
        raise ValueError("primary=True requires subtype")

    subtype_match = partial(_matches_subtype, subtype=subtype, primary=primary)
    type_match = lambda module: type is None or module.type == type
    loop_match = lambda module: loopable is None or module.loopable is loopable
    category_match = lambda module: (
        category is None or get_module_category(module) == category
    )
    provider_match = lambda module: provider is None or module.provider == provider
    matches = subtype_match, type_match, loop_match, category_match, provider_match
    match = lambda module: all(is_match(module) for is_match in matches)

    # built-ins first, then registry (runtime + entry-point) modules shadow them
    catalog = {metadata.name: metadata for metadata in gen_module_catalog()}
    catalog.update((metadata.name, metadata) for metadata in gen_registry_catalog())

    # dynamic filter module import shadows the builtin filter
    filtered = builtins.filter(match, catalog.values())
    modules = sorted(filtered, key=lambda module: module.name)
    return modules if show_metadata else [module.name for module in modules]


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
        definition: ModuleDefinition | None = module_registry.load_definition(canonical)

        if definition is None:  # noqa: SIM102
            if module := import_or_else(f"{_PACKAGE}.{canonical}"):
                definition = ModuleDefinition.from_module(module, name=canonical)
    else:
        definition = None

    return definition
