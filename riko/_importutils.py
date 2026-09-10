# vim: sw=4:ts=4:expandtab
"""
riko._metadata
"""

from collections.abc import Callable
from importlib import import_module
from types import ModuleType

from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.types._wrappers import Interface, Pipe

type Loader = Callable[[str], ModuleType | None]


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


def resolve_interface(
    name: str,
    is_async: bool = False,
    builtin: bool = True,
    loader: Loader | None = None,
) -> Pipe:
    import_name = f"riko.modules.{name}" if builtin else name
    loader = loader or import_or_else

    if module := loader(import_name):
        interface: Interface = "async_pipe" if is_async else "pipe"

        if (pipe := getattr(module, interface, None)) is None:
            raise UnsupportedPipelineError(f"{name!r} has no {interface!r}")
    else:
        raise UnsupportedModuleError(name)

    return pipe
