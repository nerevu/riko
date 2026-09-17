# vim: sw=4:ts=4:expandtab
"""
Built-in riko modules and module-author utilities.

Most users interact with modules through ``SyncPipe`` or ``AsyncPipe``.
Extension authors should prefer the supported contracts in ``riko.ext``.
"""

from riko.types.modules import ModuleMetadata, ModuleSubtype, ModuleType

from ._decorators import operator, processor, splitter
from ._metadata import describe_module, get_module_metadata

__all__ = [
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "describe_module",
    "get_module_metadata",
    "operator",
    "processor",
    "splitter",
]
