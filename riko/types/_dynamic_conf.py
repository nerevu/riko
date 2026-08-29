# vim: sw=4:ts=4:expandtab
"""
riko.types._dynamic_conf
~~~~~~~~~~~~~~~

Provides hand-maintained base types for generated module configurations.
"""

from typing import Any

from riko._objectify import Objectify


class DynamicConf(Objectify[Any]):
    """
    A parsed, case-insensitive module configuration.

    Used when a module has no more specific configuration type.
    """
