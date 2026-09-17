# vim: sw=4:ts=4:expandtab
"""Expose parsed module configuration helpers to extension authors."""

from typing import get_type_hints

from riko.coercion._dynamic_conf import DynamicConf


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
