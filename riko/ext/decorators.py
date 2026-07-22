# vim: sw=4:ts=4:expandtab
"""
riko.ext.decorators
~~~~~~~~~~~~~~~~~~~~
Pipe-authoring decorators surfaced for extension authors. The implementation
lives in :mod:`riko.modules`; this module is a stable re-export point that
survives the planned relocation to ``riko.modules._decorators`` (Phase 3).
"""

from riko.modules import operator, processor, splitter

__all__ = ["operator", "processor", "splitter"]
