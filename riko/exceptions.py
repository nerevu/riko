# vim: sw=4:ts=4:expandtab
"""
Provides riko specific exceptions
"""


class RikoError(Exception):
    """Base class for Riko-specific errors."""


class ModuleError(RikoError):
    """Base class for module-related errors."""


class UnsupportedModuleError(ModuleError):
    def __init__(self, module_name: str):
        super().__init__(f"Unsupported riko module: {module_name}")
        self.module_name = module_name


class PipelineError(RikoError):
    """Base class for pipeline-related errors."""


class UnsupportedPipelineError(PipelineError):
    def __init__(self, pipe_id: str):
        super().__init__(f"Unsupported riko subpipeline: {pipe_id}")
        self.pipe_id = pipe_id


class PipelineStateError(PipelineError):
    def __init__(self, state: str, action: str):
        super().__init__(f"cannot {action} a pipe in state {state!r}")
        self.state = state
        self.action = action


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


__all__ = [
    "DuplicateReceiverError",
    "ModuleError",
    "PipelineError",
    "PipelineStateError",
    "PubSubError",
    "ReceiverUnavailableError",
    "RikoError",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
]
