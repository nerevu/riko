# vim: sw=4:ts=4:expandtab
"""
Private execution runtime for running prepared workflows.

This package owns the one-shot sync/async executions that turn an immutable
execution plan into a run. Each execution owns the exit stack and sync/async bridge
for that run; these are internal implementation details and are not part of any
supported import surface.
"""
