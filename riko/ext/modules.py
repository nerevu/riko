# vim: sw=4:ts=4:expandtab
"""
Provides module authoring for extension authors.

This namespace contains pipe decorators, module definitions, module registration, module
metadata and naming types, wrapper protocols, and configuration helpers. It is part of
the SemVer-guaranteed ``riko.ext`` surface. Every name here is also re-exported from
``riko.ext``.

Examples:

    Basic usage::

        >>> from riko.ext import ModuleDefinition, ModuleRegistry
        >>>
        >>> def double(stream, **kwargs):
        ...     return ({"x": item["x"] * 2} for item in stream)
        >>>
        >>> registry = ModuleRegistry()
        >>> registry.register(ModuleDefinition(name="double", sync_pipe=double))
        >>> list(registry.require("double")([{"x": 2}]))
        [{'x': 4}]

"""

from inspect import unwrap
from types import SimpleNamespace

from riko.base._typing import resolve_type_hints
from riko.coercion import _configs
from riko.coercion._dynamic_conf import DynamicConf
from riko.definitions.modules import ModuleDefinition, normalize_module_name
from riko.modules._decorators import operator, processor, splitter
from riko.modules._metadata import get_module_category
from riko.runtime._module_registry import (
    ModuleRegistry,
    register_module,
    reset_module_registry,
)
from riko.types._enums import ModuleName, ModuleNameLike
from riko.types._wrappers import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    ModuleWrapper,
    PreparedCall,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)
from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType


def get_conf_type(parser: object) -> type[DynamicConf]:
    """
    Resolves the configuration type a parser declares for its ``objconf``.

    Annotations written as strings, including names imported only for type
    checking, resolve against the generated module configuration types.

    Args:

        parser: The module parser whose ``objconf`` annotation to read.

    Returns:

        The annotated ``DynamicConf`` subclass, or ``DynamicConf`` itself when the
        parser declares no resolvable configuration type.

    Examples:

        >>> from riko.ext import DynamicConf, get_conf_type
        >>>
        >>> def parser(objconf: DynamicConf):
        ...     return objconf
        >>>
        >>> get_conf_type(parser) is DynamicConf
        True

        >>> from riko.modules.fetch import parser as fetch_parser
        >>>
        >>> get_conf_type(fetch_parser).__name__
        'FetchObjconf'
        >>> # without a resolvable objconf annotation, a parser gets DynamicConf
        >>> def unannotated(objconf):
        ...     return objconf
        >>>
        >>> def unresolvable(objconf: "Missing"):  # noqa: F821
        ...     return objconf
        >>>
        >>> get_conf_type(unannotated) is get_conf_type(unresolvable) is DynamicConf
        True

    """
    target = unwrap(parser) if callable(parser) else parser
    annotations = getattr(target, "__annotations__", None) or {}

    if (objconf := annotations.get("objconf")) is not None:
        globalns = getattr(target, "__globals__", {})
        annots = {"objconf": objconf}
        stub = SimpleNamespace(__annotations__=annots, __globals__=globalns)

        try:
            hint = resolve_type_hints(stub, _configs).get("objconf")
        except (NameError, TypeError, SyntaxError):
            hint = None
    else:
        hint = None

    if isinstance(hint, type) and issubclass(hint, DynamicConf):
        conf_type = hint
    else:
        conf_type = DynamicConf

    return conf_type


__all__ = [
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "DynamicConf",
    "ModuleDefinition",
    "ModuleMetadata",
    "ModuleName",
    "ModuleNameLike",
    "ModuleRegistry",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "PreparedCall",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "get_conf_type",
    "get_module_category",
    "normalize_module_name",
    "operator",
    "processor",
    "register_module",
    "reset_module_registry",
    "splitter",
]
