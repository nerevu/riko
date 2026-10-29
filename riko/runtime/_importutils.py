# vim: sw=4:ts=4:expandtab
"""Resolves the sync or async pipe interfaces of modules and stored workflows."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import TYPE_CHECKING

from riko.base._exceptions import UnsupportedModuleError, UnsupportedWorkflowError
from riko.base._typing import import_or_else

if TYPE_CHECKING:
    from riko.types._wrappers import AnyModuleWrapper, Interface

type Loader = Callable[[str], ModuleType | None]


def _load_module(
    name: str, builtin: bool = True, loader: Loader | None = None
) -> ModuleType:
    import_name = f"riko.modules.{name}" if builtin else name
    loader = loader or import_or_else

    if (module := loader(import_name)) is None and builtin:
        raise UnsupportedModuleError(name)
    elif module is None:
        raise UnsupportedWorkflowError(name, "no store supplies it")

    return module


def require_interface(
    name: str,
    is_async: bool = False,
    builtin: bool = True,
    loader: Loader | None = None,
) -> AnyModuleWrapper:
    module = _load_module(name, builtin, loader)
    interface: Interface = "async_pipe" if is_async else "pipe"

    if (pipe := getattr(module, interface, None)) is None:
        error = UnsupportedModuleError if builtin else UnsupportedWorkflowError
        raise error(name, f"it has no {interface!r}")

    return pipe


def load_interfaces(
    name: str, builtin: bool = True, loader: Loader | None = None
) -> frozenset[Interface]:
    """
    Loads which of ``pipe`` and ``async_pipe`` a module defines.

    Args:

        name: Module name to load.
        builtin: Whether ``name`` is a built-in ``riko.modules`` module.
        loader: Optional module loader overriding the default import.

    Returns:

        The subset of ``pipe``/``async_pipe`` the module exposes.

    Raises:

        UnsupportedModuleError: If ``builtin`` and ``name`` cannot be imported.

        UnsupportedWorkflowError: If not ``builtin`` and ``loader`` finds no ``name``.

    """
    module = _load_module(name, builtin, loader)
    available: set[Interface] = set()

    if getattr(module, "pipe", None) is not None:
        available.add("pipe")

    if getattr(module, "async_pipe", None) is not None:
        available.add("async_pipe")

    return frozenset(available)
