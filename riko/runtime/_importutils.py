# vim: sw=4:ts=4:expandtab
"""
Resolves sync or async pipe interfaces from importable modules.
"""

from collections.abc import Callable
from types import ModuleType

from riko.base._imports import import_or_else
from riko.base.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.types._wrappers import Interface, Pipe

type Loader = Callable[[str], ModuleType | None]


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
