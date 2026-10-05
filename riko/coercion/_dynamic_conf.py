# vim: sw=4:ts=4:expandtab
"""
Provides hand-maintained base types for generated module configurations.

Examples:

    Basic usage::

        >>> from riko.ext import DynamicConf
        >>>
        >>> conf = DynamicConf({"NAME": "riko"})
        >>> conf.name
        'riko'

"""

from __future__ import annotations

from typing import Any

from ._objectify import Objectify


class DynamicConf(Objectify[Any]):
    """
    A parsed, case-insensitive module configuration.

    Used when a module has no more specific configuration type.
    """
