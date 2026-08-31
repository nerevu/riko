# vim: sw=4:ts=4:expandtab
"""
Registers a built-in module under a second name with the ``module=`` convention.

Point a ``ModuleDefinition`` at any object exposing ``pipe`` / ``async_pipe`` and
the registry reads both interfaces off it. Here we give the built-in ``count`` a
second, namespaced name without touching riko core.

For explicit interface callables, see ``register_module.py``. For the packaged
entry-point plugin path, see ``riko-example-ext/``.

Examples:
    Run it::

        python examples/register_alias.py

"""

from riko import SyncPipe
from riko.ext import ModuleDefinition, register
from riko.modules import count

if __name__ == "__main__":
    register(ModuleDefinition(name="stats.count", module=count))
    print(list(SyncPipe("stats.count", source=[{"n": 1}, {"n": 2}, {"n": 3}])))
