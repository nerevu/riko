# vim: sw=4:ts=4:expandtab
"""
riko.ext.config
~~~~~~~~~~~~~~~
Parsed module configuration for extension authors. ``DynamicConf`` is the
case-insensitive attribute/mapping bag that every parsed config is; it is the
fallback used when a parser declares no precise config type. A module may declare
a precise config by subclassing ``DynamicConf`` and annotating its ``objconf``
parameter with it; ``get_conf_type`` derives that type from the annotation.
"""

from typing import get_type_hints

from riko import DynamicConf


def get_conf_type(parser: object) -> type[DynamicConf]:
    try:
        annotation = get_type_hints(parser).get("objconf")
    except (NameError, TypeError):
        annotation = None

    if isinstance(annotation, type) and issubclass(annotation, DynamicConf):
        conf_type = annotation
    else:
        conf_type = DynamicConf

    return conf_type


__all__ = ["DynamicConf", "get_conf_type"]
