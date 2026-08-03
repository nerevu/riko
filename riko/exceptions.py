# vim: sw=4:ts=4:expandtab
"""
Provides riko specific exceptions
"""


class UnsupportedModuleError(ImportError):
    def __init__(self, module_name: str):
        super().__init__(f"Unsupported riko module: {module_name}")
        self.module_name = module_name


class UnsupportedPipelineError(ValueError):
    def __init__(self, pipe_id: str):
        super().__init__(f"Unsupported riko subpipeline: {pipe_id}")
        self.pipe_id = pipe_id


class PipelineStateError(Exception):
    def __init__(self, state: str, action: str):
        super().__init__(f"cannot {action} a pipe in state {state!r}")
        self.state = state
        self.action = action


class ReceiverUnavailableError(Exception):
    def __init__(self, name: str):
        super().__init__(f"pub/sub receiver {name!r} was never subscribed")
        self.name = name


class DuplicateReceiverError(Exception):
    def __init__(self, name: str):
        super().__init__(f"pub/sub receiver {name!r} already has an active subscriber")
        self.name = name


__all__ = [
    "DuplicateReceiverError",
    "PipelineStateError",
    "ReceiverUnavailableError",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
]
