# vim: sw=4:ts=4:expandtab
"""
Runtime registration with the ``module=`` **convention** — point a
``ModuleDefinition`` at any object exposing ``pipe`` / ``async_pipe`` and the
registry reads both interfaces off it. Here we give the built-in ``count`` a
second, namespaced name without touching riko core.

(For explicit interface callables, see ``register_module.py``. For the packaged
entry-point plugin path, see ``riko-example-ext/``.)

Run it::

    python examples/register_alias.py
"""

from riko import SyncPipe
from riko.ext import ModuleDefinition, register
from riko.modules import count

register(ModuleDefinition(name="stats.count", module=count))


if __name__ == "__main__":
    # 'stats.count' now resolves to the built-in count pipe
    print(list(SyncPipe("stats.count", source=[{"n": 1}, {"n": 2}, {"n": 3}])))
