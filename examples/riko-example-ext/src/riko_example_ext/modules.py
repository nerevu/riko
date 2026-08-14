# vim: sw=4:ts=4:expandtab
"""
The extension's registry surface. The entry point in ``pyproject.toml`` points
here; ``shout_definition`` is what riko's ``ModuleRegistry`` loads and resolves.
"""

from riko.ext import ModuleDefinition
from riko_example_ext import shout

# Point at the module; riko reads ``pipe``/``async_pipe`` off it by the same
# convention as a built-in — no need to list the callables individually. The
# canonical ``name`` is omitted: the registry stamps it from the entry-point key
# (``example.shout`` in pyproject.toml), keeping one source of truth.
description = "Uppercase the 'content' field — example riko extension module."
shout_definition = ModuleDefinition(module=shout, description=description)
