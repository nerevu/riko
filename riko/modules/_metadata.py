# vim: sw=4:ts=4:expandtab
"""
Derives and lists metadata for built-in and registered modules.

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
from typing import TYPE_CHECKING, overload

from riko.base._guards import is_callable
from riko.base._typing import import_or_else
from riko.definitions._module_definition import ModuleDefinition, normalize_module_name
from riko.runtime._module_registry import module_registry
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types._wrappers import WRAPPER_META, is_wrapper_meta, require_wrapper_meta
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


def _metadata_from_targets(
    name: str, targets: tuple[WrapperMeta, ...], *, label: str, strict_naming: bool
) -> ModuleMetadata | None:
    attrs = tuple(attr for attr in WRAPPER_META if attr != "isasync")

    if len(targets) == 2:
        for attr in attrs:
            actual, expected = [getattr(targets[pos], attr) for pos in [0, 1]]

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


def _load_registry_metadata(name: str) -> ModuleMetadata | None:
    if definition := module_registry.load_definition(name):
        pipes = filter(is_callable, map(definition.get_pipe, (True, False)))
    else:
        pipes = ()

    require = partial(require_wrapper_meta, what=f"{name} pipe")

    try:
        args = (name, tuple(map(require, pipes)))
        metadata = _metadata_from_targets(*args, label=name, strict_naming=False)
    except (AttributeError, TypeError):
        # a callable that isn't a metadata-carrying pipe wrapper (e.g. a
        # bare lambda) — resolvable, but not catalogable
        metadata = None

    return metadata


def get_module_metadata(name: ModuleNameLike) -> ModuleMetadata | None:
    """
    Derives a module's metadata from its pipe callables.

    A registered module shadows a built-in of the same name.

    Args:

        name: Module name.

    Returns:

        The module's metadata, or ``None`` when the name is not a module or the module
        declares no metadata.

    Raises:

        TypeError: When the module's pipe lacks module metadata, or its sync and
            async pipes disagree about their metadata.

    Examples:

        >>> get_module_metadata("count").type
        'operator'
        >>> get_module_metadata("does-not-exist")

    """
    if canonical := normalize_module_name(name):
        definition = module_registry.load_definition(canonical)
        builtin = definition is None
        module = import_or_else(f"{_PACKAGE}.{canonical}") if builtin else None
    else:
        builtin, module = False, None

    if not builtin:
        metadata = _load_registry_metadata(canonical)
    elif module is None:
        metadata = None
    else:
        names = ("pipe", "async_pipe")
        pipes = filter(is_callable, (getattr(module, name, None) for name in names))
        label = module.__name__
        require = partial(require_wrapper_meta, what=f"{label} pipe")
        args = (canonical, tuple(map(require, pipes)))
        metadata = _metadata_from_targets(*args, label=label, strict_naming=True)

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
    for name in module_registry.discovered_names:
        if metadata := _load_registry_metadata(name):
            yield metadata


def _matches_subtype(
    module: ModuleMetadata, subtype: ModuleSubtype | str | None, *, primary: bool
) -> bool:
    if subtype is None:
        matched = True
    elif primary:
        matched = module.subtype == subtype
    else:
        matched = subtype in SUBTYPES and module.supports(subtype)

    return matched


def list_module_metadata(
    *,
    type: ModuleType | str | None = None,
    subtype: ModuleSubtype | str | None = None,
    category: ModuleCategory | str | None = None,
    provider: str | None = None,
    primary: bool = False,
    loopable: bool | None = None,
) -> list[ModuleMetadata]:
    """
    Lists the metadata of the modules that match the given filters.

    Built-in modules are listed alongside registered and entry-point modules; a
    registered module shadows a built-in of the same name.

    Kwargs:

        type: Only list modules of this module type (e.g., ``"operator"``).
        subtype: Only list modules that support this subtype (e.g., ``"aggregator"``).
        category: Only list modules in this discovery category (e.g., ``"source"``).
        provider: Only list modules from this provider (e.g., ``"riko"`` for built-ins).
        primary: Whether ``subtype`` must be marked as primary (default: False).
        loopable: List modules with matching loopability (or all modules when ``None``).

    Returns:

        The matching modules' metadata, sorted by name.

    Raises:

        ValueError: When ``type`` and ``subtype`` are both given, or ``primary`` is set
            and ``subtype`` is not.

    Examples:

        >>> from riko import list_module_metadata
        >>>
        >>> aggregators = list_module_metadata(subtype="aggregator", primary=True)
        >>> [(metadata.name, metadata.type) for metadata in aggregators]
        [('count', 'operator'), ('sum', 'operator')]
        >>> [metadata.name for metadata in list_module_metadata(category="sink")]
        ['write']

    """
    if type and subtype:
        raise ValueError("type and subtype cannot be combined")
    elif primary and not subtype:
        raise ValueError("primary=True requires subtype")

    def match(module: ModuleMetadata) -> bool:
        return (
            (type is None or module.type == type)
            and (loopable is None or module.loopable is loopable)
            and (category is None or module.category == category)
            and (provider is None or module.provider == provider)
            and _matches_subtype(module, subtype=subtype, primary=primary)
        )

    # built-ins first, then registry (runtime + entry-point) modules shadow them
    catalog = {metadata.name: metadata for metadata in gen_module_catalog()}
    catalog.update((metadata.name, metadata) for metadata in gen_registry_catalog())

    # dynamic filter module import shadows the builtin filter
    filtered = builtins.filter(match, catalog.values())
    return sorted(filtered, key=lambda module: module.name)


def list_modules(
    *,
    type: ModuleType | str | None = None,
    subtype: ModuleSubtype | str | None = None,
    category: ModuleCategory | str | None = None,
    provider: str | None = None,
    primary: bool = False,
    loopable: bool | None = None,
) -> list[str]:
    """
    Lists the names of the modules that match the given filters.

    Takes the same filters as :func:`list_module_metadata`.

    Kwargs:

        type: Only list modules of this module type (e.g., ``"operator"``).
        subtype: Only list modules that support this subtype (e.g., ``"aggregator"``).
        category: Only list modules in this discovery category (e.g., ``"source"``).
        provider: Only list modules from this provider (e.g., ``"riko"`` for built-ins).
        primary: Whether ``subtype`` must be marked as primary (default: False).
        loopable: List modules with matching loopability (or all modules when ``None``).

    Returns:

        The matching module names, sorted.

    Raises:

        ValueError: When ``type`` and ``subtype`` are both given, or ``primary`` is set
            and ``subtype`` is not.

    Examples:

        >>> list_modules(subtype="aggregator", primary=True)
        ['count', 'sum']
        >>> list_modules(category="sink")
        ['write']
        >>> list_modules(provider="riko") == list_modules()
        True

    """
    metadata = list_module_metadata(
        type=type,
        subtype=subtype,
        category=category,
        provider=provider,
        primary=primary,
        loopable=loopable,
    )
    return [module.name for module in metadata]


@overload
def describe_module(name: WrapperMeta) -> ModuleDefinition: ...
@overload
def describe_module(name: ModuleNameLike | None) -> ModuleDefinition | None: ...
def describe_module(
    name: WrapperMeta | ModuleNameLike | None,
) -> ModuleDefinition | None:
    """
    Describes a module, stored workflow, or pipe; or reports None when unknown.

    A built-in module name is described from its module. A stored workflow's
    ``pipe_<id>`` name (or ``pipe:<id>`` alias) is looked up in the  workflow stores. A
    pipe callable is described from its metadata.

    Args:

        name: The module name, stored workflow's ``pipe_<id>`` name, or a pipe callable.

    Returns:

        The module definition, or None when no module or stored workflow for ``name``
        exists. Its ``input_schemas`` and ``dependencies`` report what the workflow
        reads and runs.

    Raises:

        InvalidPipelineError: If a workflow store holds a malformed
            ``WorkflowDocument`` named ``name``, or the stored workflow embeds itself
            through the workflows its nodes name.

        UnsupportedWorkflowError: If a document store supplies ``name`` but no
            dispatcher is registered to run it.

    Examples:

        >>> from riko import Sources
        >>> from riko.ext import register_workflow_store, temporary_registrations
        >>> from riko.modules.fetch import pipe as fetch

        # by module name
        >>> module_def = describe_module(Sources.FETCH)
        >>> module_def.name
        'fetch'
        >>> module_def.description
        'Fetches an RSS feed and yields feed entries.'
        >>> module_def.sync_pipe.__module__
        'riko.modules.fetch'
        >>> module_def.dependencies
        ()
        >>> describe_module("does-not-exist")

        # by stored workflow
        >>> with temporary_registrations():
        ...     register_workflow_store(package="examples.pyworkflows", replace=True)
        ...     describe_module("pipe:timezone").dependencies
        ...     describe_module("pipe:timezone").input_schemas
        ('dateformat', 'itembuilder')
        FrozenDict({})

        # by pipe callable
        >>> describe_module(fetch).name
        'fetch'

    """
    if is_wrapper_meta(name):  # pipe
        definition: ModuleDefinition | None = ModuleDefinition.from_pipe(name)
    elif canonical := normalize_module_name(name):  # module name
        definition = module_registry.load_definition(canonical)
        module = import_or_else(f"{_PACKAGE}.{canonical}")

        if definition is None and module is not None:
            definition = ModuleDefinition.from_module(module, name=canonical)

        is_stored = definition is None and workflow_resolver.is_compatible(canonical)

        if is_stored and (stored := workflow_resolver.load(canonical)) is not None:
            definition = ModuleDefinition.from_module(stored)  # stored workflow
    else:
        definition = None

    return definition
