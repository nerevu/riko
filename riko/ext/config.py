# vim: sw=4:ts=4:expandtab
"""
Exposes parsed module configuration helpers to extension authors.

Examples:

    Basic usage::

        >>> from riko.ext import DynamicConf, get_conf_type
        >>>
        >>> def parser(objconf: DynamicConf):
        ...     return objconf
        >>>
        >>> get_conf_type(parser) is DynamicConf
        True

"""

from inspect import unwrap
from types import SimpleNamespace

from riko.base._typing import resolve_type_hints
from riko.coercion import _configs
from riko.coercion._dynamic_conf import DynamicConf


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

        >>> from riko.modules.fetch import parser
        >>>
        >>> get_conf_type(parser).__name__
        'FetchObjconf'

    """
    target = unwrap(parser) if callable(parser) else parser
    annotations = getattr(target, "__annotations__", None) or {}

    if "objconf" in annotations:
        globalns = getattr(target, "__globals__", {})
        stub = SimpleNamespace(
            __annotations__={"objconf": annotations["objconf"]}, __globals__=globalns
        )

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


__all__ = ["DynamicConf", "get_conf_type"]
