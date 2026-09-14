# vim: sw=4:ts=4:expandtab
"""
riko.coercion._dynamic_conf
~~~~~~~~~~~~~~~

Provides hand-maintained base types for generated module configurations.
"""

from __future__ import annotations

from typing import Any

from ._objectify import Objectify


class DynamicConf(Objectify[Any]):
    """
    A parsed, case-insensitive module configuration.

    Used when a module has no more specific configuration type.
    """
