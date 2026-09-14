from importlib import import_module
from types import ModuleType

from .exceptions import ImportLintError


def import_or_else(target: str) -> ModuleType | None:
    try:
        module = import_module(target)
    except ModuleNotFoundError as e:
        module = None

        if missing_name := e.name:
            is_target = target == missing_name

            if not (is_target or target.startswith(f"{missing_name}.")):
                raise

    return module


def _run_check():
    try:
        pass
    except ImportLintError:
        pass
