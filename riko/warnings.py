# vim: sw=4:ts=4:expandtab
"""
Provides riko specific warnings
"""


class RikoWarning(UserWarning):
    """Base class for Riko-specific errors."""


class ResourceInterpretationWarning(RikoWarning):
    """Warning for resource interpretation issues."""


__all__ = ["ResourceInterpretationWarning", "RikoWarning"]
