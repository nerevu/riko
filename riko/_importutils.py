# vim: sw=4:ts=4:expandtab
"""
riko._metadata
"""

from importlib import import_module


def import_or_else(target):
    try:
        module = import_module(target)
    except ModuleNotFoundError as e:
        module = None

        if missing_name := e.name:
            is_target = target == missing_name

            if not (is_target or target.startswith(f"{missing_name}.")):
                raise

    return module
