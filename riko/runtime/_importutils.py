# vim: sw=4:ts=4:expandtab
"""Resolves sync or async pipe interfaces from importable modules."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import TYPE_CHECKING

from riko.base._imports import import_or_else
from riko.base.exceptions import UnsupportedModuleError, UnsupportedPipelineError

if TYPE_CHECKING:
    from riko.types._wrappers import Interface, Pipe

type Loader = Callable[[str], ModuleType | None]


def _load_module(
    name: str, builtin: bool = True, loader: Loader | None = None
) -> ModuleType:
    import_name = f"riko.modules.{name}" if builtin else name
    loader = loader or import_or_else

    if (module := loader(import_name)) is None:
        raise UnsupportedModuleError(name)

    return module


def resolve_interface(
    name: str,
    is_async: bool = False,
    builtin: bool = True,
    loader: Loader | None = None,
) -> Pipe:
    module = _load_module(name, builtin, loader)
    interface: Interface = "async_pipe" if is_async else "pipe"

    if (pipe := getattr(module, interface, None)) is None:
        raise UnsupportedPipelineError(f"{name!r} has no {interface!r}")

    return pipe


def load_interfaces(
    name: str, builtin: bool = True, loader: Loader | None = None
) -> frozenset[Interface]:
    """
    Loads which of a module's sync and async interfaces are defined.

    Args:

        name: Module name to load.
        builtin: Whether ``name`` is a built-in ``riko.modules`` module.
        loader: Optional module loader overriding the default import.

    Returns:

        The subset of ``pipe``/``async_pipe`` the module exposes.

    Raises:

        UnsupportedModuleError: If ``name`` cannot be imported.

    """
    module = _load_module(name, builtin, loader)
    available: set[Interface] = set()

    if getattr(module, "pipe", None) is not None:
        available.add("pipe")

    if getattr(module, "async_pipe", None) is not None:
        available.add("async_pipe")

    return frozenset(available)
