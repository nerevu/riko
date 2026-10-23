# vim: sw=4:ts=4:expandtab
"""
Registers a built-in module under a second name with ``ModuleDefinition.from_module``.

Point ``from_module`` at any object exposing ``pipe``/``async_pipe`` and it registers
both interfaces. Here we give the built-in ``count`` a second, namespaced name without
touching riko core.

For explicit interface callables, see ``register_module.py``. For the installable
extension package, see ``riko-example-ext/``.

Examples:

    Run it::

        python examples/register_alias.py

"""

from riko import Pipeline
from riko.ext import ModuleDefinition, register_module
from riko.modules import count

if __name__ == "__main__":
    register_module(ModuleDefinition.from_module(count, name="stats.count"))
    source = [{"n": 1}, {"n": 2}, {"n": 3}]
    print(list(Pipeline(source=source).pipe("stats.count")))
