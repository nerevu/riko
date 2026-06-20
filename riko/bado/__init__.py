# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado import react

"""

try:
    from twisted.internet.task import react
except ImportError:
    react = lambda _, _reactor=None: None
    backend = "empty"
else:
    backend = "twisted"


class Reactor:
    fake = False


reactor = Reactor()
_issync = backend == "empty"
_isasync = not _issync
