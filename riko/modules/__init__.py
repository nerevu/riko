# vim: sw=4:ts=4:expandtab
"""
Built-in riko modules and their catalog.

Most users interact with modules through ``Pipeline``. The catalog describes the
built-in modules and their metadata. Extension authors import authoring contracts from
``riko.ext``.
"""

from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

from ._metadata import describe_module, get_module_metadata

__all__ = [
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "describe_module",
    "get_module_metadata",
]
