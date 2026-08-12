# vim: sw=4:ts=4:expandtab
"""
riko.ext.names
~~~~~~~~~~~~~~
Typed module-name discovery. Strings stay the canonical runtime identifier;
enums are an optional, type-safe layer over them.

``ModuleName`` is a deliberately empty ``StrEnum`` base. Generated per-package
enums (built-in and extension) subclass it, so any of their members is accepted
anywhere riko accepts a module name. ``normalize_module_name`` collapses either
form back to the plain string identifier at the public boundary, so the resolver
never sees an enum.
"""

from enum import StrEnum

type ModuleNameLike = str | ModuleName


class ModuleName(StrEnum):
    """Base type accepted anywhere riko accepts a module name."""


def normalize_module_name(name: ModuleNameLike | None) -> str | None:
    """Collapse a ``str``/``ModuleName`` (or ``None``) to its canonical string."""
    return name.value if isinstance(name, ModuleName) else name
