# vim: sw=4:ts=4:expandtab
"""
Defines riko's exceptions and warnings.

The public import path is ``riko.base.exceptions``, which re-exports every class here
and names them as its own.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

type _Call = tuple[tuple[object, ...], dict[str, object]]


def _get_detail(*parts: str | None) -> str:
    joined = "; ".join(filter(None, parts))
    return f" ({joined})" if joined else ""


def _rebuild[E: RikoError](
    cls: type[E], args: tuple[object, ...], kwargs: dict[str, object]
) -> E:
    return cls(*args, **kwargs)


class RikoError(Exception):
    """
    Base class for Riko-specific errors.

    Every riko error pickles and copies intact, so one raised in a worker process
    reaches the caller with its message and attributes unchanged.

    Examples:

        >>> import pickle
        >>>
        >>> error = pickle.loads(pickle.dumps(InvalidPipelineError("bad")))
        >>> str(error), error.msg
        ('Invalid pipeline: bad', 'bad')

    """

    _call: _Call

    def __new__(cls, *args: object, **kwargs: object) -> Self:
        error = super().__new__(cls, *args)
        error._call = (args, kwargs)
        return error

    def __reduce__(
        self,
    ) -> tuple[Callable[..., Self], tuple[type[Self], *_Call], dict[str, object]]:
        return (_rebuild, (type(self), *self._call), self.__dict__)


class ModuleError(RikoError):
    """Base class for module-related errors."""


class UnsupportedModuleError(ModuleError):
    """
    Reports an unusable module name with hints for close matches.

    Args:

        module_name: The unresolved module name.
        reason: Why the module is unusable (if it exists but lacks something).
        candidates: Known module names to suggest from.

    Attributes:

        module_name: The unresolved module name.
        reason: Why the module is unusable, or None.
        matches: The candidates that closely match ``module_name``, closest first.

    Examples:

        >>> str(UnsupportedModuleError("trunkate", candidates=["truncate", "split"]))
        "Unsupported riko module: trunkate (did you mean 'truncate'?)"

    """

    def __init__(
        self,
        module_name: str,
        reason: str | None = None,
        *,
        candidates: Iterable[str] = (),
    ):
        matches = tuple(get_close_matches(module_name, tuple(candidates), n=3))
        joined = ", ".join(map(repr, matches))
        hint = f"did you mean {joined}?" if joined else None
        detail = _get_detail(reason, hint)

        super().__init__(f"Unsupported riko module: {module_name}{detail}")
        self.module_name = module_name
        self.reason = reason
        self.matches: tuple[str, ...] = matches
        self._call = ((module_name, reason), {"candidates": matches})


class TargetError(RikoError):
    """Base class for target-related errors."""


class UnsupportedTargetError(TargetError):
    def __init__(self, target: str):
        super().__init__(f"Unsupported riko target: {target}")
        self.target = target


class PipelineError(RikoError):
    """Base class for pipeline-related errors."""


class UnsupportedWorkflowError(PipelineError):
    def __init__(self, pipe_id: str, reason: str | None = None):
        detail = _get_detail(reason)
        super().__init__(f"Unsupported riko stored workflow: {pipe_id}{detail}")
        self.pipe_id = pipe_id
        self.reason = reason


class PipelineStateError(PipelineError):
    def __init__(self, state: str, action: str, *, subject: str):
        super().__init__(f"cannot {action} the {subject} in state {state!r}")
        self.state = state
        self.action = action
        self.subject = subject


class InvalidPipelineError(PipelineError):
    """Raised when a workflow is malformed or cannot be executed as declared."""

    def __init__(self, msg: str):
        super().__init__(f"Invalid pipeline: {msg}")
        self.msg = msg


class EmptyPipelineError(PipelineError, LookupError):
    """Raised when a pipeline asked for its first item produces none."""

    def __init__(self) -> None:
        super().__init__("pipeline produced no items")


class PubSubError(RikoError):
    """Base class for pub/sub errors."""


class ReceiverUnavailableError(PubSubError):
    def __init__(self, name: str):
        super().__init__(f"pub/sub receiver {name!r} was never subscribed")
        self.name = name


class DuplicateReceiverError(PubSubError):
    def __init__(self, name: str):
        super().__init__(f"pub/sub receiver {name!r} already has an active subscriber")
        self.name = name


class IdentityError(RikoError):
    """Base class for canonical-identity errors."""


class IdentityEncodingError(IdentityError):
    def __init__(self, obj_type: type):
        super().__init__(
            f"cannot canonically encode value of type {obj_type.__name__!r}"
        )
        self.obj_type = obj_type


class CyclicIdentityError(IdentityError):
    def __init__(self):
        super().__init__("cannot canonically encode a cyclic structure")


class ImportLintError(RikoError): ...


class ImportAnalysisError(ImportLintError): ...


class InvalidArchitectureError(ImportLintError): ...


class RikoWarning(UserWarning):
    """Base class for Riko-specific warnings."""


class ResourceInterpretationWarning(RikoWarning):
    """Warns that a resource definition may be interpreted unexpectedly."""


__all__ = [
    "CyclicIdentityError",
    "DuplicateReceiverError",
    "EmptyPipelineError",
    "IdentityEncodingError",
    "IdentityError",
    "ImportAnalysisError",
    "ImportLintError",
    "InvalidArchitectureError",
    "InvalidPipelineError",
    "ModuleError",
    "PipelineError",
    "PipelineStateError",
    "PubSubError",
    "ReceiverUnavailableError",
    "ResourceInterpretationWarning",
    "RikoError",
    "RikoWarning",
    "TargetError",
    "UnsupportedModuleError",
    "UnsupportedTargetError",
    "UnsupportedWorkflowError",
]

# Tracebacks and pickles name the public module these are imported from.
for _name in __all__:
    globals()[_name].__module__ = "riko.base.exceptions"
