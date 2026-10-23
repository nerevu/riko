# vim: sw=4:ts=4:expandtab
"""
Provides guards for a module's required keyword arguments and conf keys.

A required keyword argument or conf key that is missing is a call-site programming error
rather than a runtime data condition. This is why these guards raise instead of degrade.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from riko.coercion._dynamic_conf import DynamicConf


def require_arg[T](value: T | None, name: str, module: str, strict: bool = False) -> T:
    """
    Narrows a module's required keyword argument to ``T`` and raises when it is omitted.

    The argument is one that a module's ``pipe`` passes on to its ``parser`` function,
    which declares it keyword-only as ``T | None = None``. Omitting it raises this
    error. The error names the module and the argument.

    Args:

        value: The supplied argument value, or ``None`` when omitted.

        name: The argument being validated, used in the error message.

        module: The module name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. an empty
            ``others`` list that would publish to nobody. Use it only where a
            falsy value can never be legitimate — never on an argument for
            which ``0``, ``False`` or ``""`` is a real value (default: False).

    Returns:

        The value, narrowed to ``T``.

    Raises:

        TypeError: If ``value`` is ``None``, or is falsy under ``strict``.

    Examples:

        >>> require_arg(len, "func", "udf")
        <built-in function len>
        >>> require_arg(None, "func", "udf")
        Traceback (most recent call last):
            ...
        TypeError: the 'udf' module requires the 'func' keyword argument

        >>> # A falsy value passes unless strict is set
        >>> require_arg([], "others", "send")
        []
        >>> require_arg([], "others", "send", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'send' module requires the 'others' keyword argument

    """
    if (value is None) or (strict and not value):
        raise TypeError(f"the {module!r} module requires the {name!r} keyword argument")

    return value


def require_conf_key[T](  # noqa: E704
    objconf: DynamicConf, key: str, module: str, strict: bool = False
) -> T:  # pyright: ignore[reportInvalidTypeVarUse]
    """
    Reads a module's required conf key and raises when the conf leaves it unset.

    Only the conf is checked. A field missing from an item is a data condition
    the module skips, not an error.

    Args:

        objconf: The parsed module configuration.

        key: The conf key that must be set.

        module: The module name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. a ``url``
            set to ``""``. Use it only where a falsy value can never be
            legitimate — never on a key for which ``0``, ``False`` or ``""`` is
            a real value (default: False).

    Returns:

        The value stored under ``key``.

    Raises:

        TypeError: If ``key`` is absent or ``None``, or is falsy under
            ``strict``.

    Examples:

        >>> from meza.fntools import Objectify
        >>>
        >>> require_conf_key(Objectify({"url": "x"}), "url", "csv")
        'x'
        >>> require_conf_key(Objectify({}), "url", "csv")
        Traceback (most recent call last):
            ...
        TypeError: the 'csv' module requires the 'url' conf key

        >>> # A falsy value passes unless strict is set
        >>> require_conf_key(Objectify({"url": ""}), "url", "csv")
        ''
        >>> require_conf_key(Objectify({"url": ""}), "url", "csv", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'csv' module requires the 'url' conf key

    """
    value = getattr(objconf, key, None)

    if (value is None) or (strict and not value):
        raise TypeError(f"the {module!r} module requires the {key!r} conf key")

    return cast("T", value)
