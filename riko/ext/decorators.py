# vim: sw=4:ts=4:expandtab
"""Expose pipe-authoring decorators to extension authors."""

from riko.modules._decorators import operator, processor, splitter

__all__ = ["operator", "processor", "splitter"]
