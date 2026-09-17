"""Optional-import helpers that distinguish missing targets from broken imports."""

from importlib import import_module
from types import ModuleType


def import_or_else(target: str) -> ModuleType | None:
    """
    Imports ``target`` or returns ``None`` when the target itself is unavailable.

    Args:

        target: Fully qualified module name to import.

    Returns:

        The imported module, or ``None`` when ``target`` or one of its parent
        packages does not exist.

    Raises:

        ModuleNotFoundError: When ``target`` resolves but importing it fails because
            one of its own dependencies is missing.

    Examples:

        >>> import_or_else("math").__name__
        'math'
        >>> import_or_else("riko.__definitely_missing__") is None
        True

    """
    try:
        module = import_module(target)
    except ModuleNotFoundError as e:
        module = None

        if missing_name := e.name:
            is_target = target == missing_name

            if not (is_target or target.startswith(f"{missing_name}.")):
                raise

    return module
