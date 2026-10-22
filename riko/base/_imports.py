"""Optional-import helpers that distinguish missing targets from broken imports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def import_or_else(target: str, *, strict: bool = False) -> ModuleType | None:
    """
    Attempts to import ``target``.

    Args:

        target: Fully qualified module name to import.

        strict: Whether a missing parent package raises instead of returning ``None``.
            When set, only ``target`` itself may be missing.

    Returns:

        The imported module, or ``None`` when ``target`` (or, unless ``strict``, one
        of its parent packages) does not exist.

    Raises:

        ModuleNotFoundError: If a module other than ``target`` is missing, and either:

            - it is not a parent package of ``target`` (such as a dependency ``target``
                imports), or
            - ``strict`` is set, so a missing parent package raises too.

            An error that names no missing module is re-raised, since nothing shows
            the missing module was ``target``.

    Examples:

        >>> import_or_else("math").__name__
        'math'
        >>> import_or_else("riko.__definitely_missing__")
        >>> import_or_else("riko.__missing__.pipe_x")
        >>> import_or_else("riko.__missing__.pipe_x", strict=True)
        Traceback (most recent call last):
        ...
        ModuleNotFoundError: No module named 'riko.__missing__'

    """
    try:
        module = import_module(target)
    except ModuleNotFoundError as e:
        module = None
        missing_name = e.name
        not_target = target != missing_name
        is_parent = missing_name is not None and target.startswith(f"{missing_name}.")

        if not_target and (strict or not is_parent):
            raise

    return module
