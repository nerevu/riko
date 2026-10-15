# vim: sw=4:ts=4:expandtab
"""
Provides target authoring for extension authors.

This namespace contains the target protocols, the built-in file target, write
capabilities, and target registration. It is part of the SemVer-guaranteed ``riko.ext``
surface. Every name here is also re-exported from ``riko.ext``.

Examples:

    Basic usage::

        >>> from riko import Backends
        >>> from riko.ext import FileTarget, TargetRegistry
        >>>
        >>> registry = TargetRegistry()
        >>> registry.resolve(Backends.FILE) is FileTarget
        True
        >>> class S3Target:
        ...     backend = Backends.S3
        >>>
        >>> registry.register(S3Target)
        >>> registry.resolve(Backends.S3) is S3Target
        True

"""

from riko.definitions._targets import FileTarget
from riko.definitions._write import WriteCapabilities
from riko.runtime._target_registry import (
    TargetRegistry,
    register_target,
    reset_target_registry,
)
from riko.types._targets import SupportsActions, SupportsRead, SupportsWrite, Target

__all__ = [
    "FileTarget",
    "SupportsActions",
    "SupportsRead",
    "SupportsWrite",
    "Target",
    "TargetRegistry",
    "WriteCapabilities",
    "register_target",
    "reset_target_registry",
]
