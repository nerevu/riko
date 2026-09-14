from dataclasses import dataclass

from riko.types._wrappers import AsyncPipeCallable, Pipe, PipeCallable, SyncPipeCallable


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """
    Defines a named module and its sync/async pipe callables.

    Callables may be given directly, or read off ``module`` on demand. This lets an
    extension point at a module exposing ``pipe``/``async_pipe`` by the same convention
    as a built-in.

    An entry point may skip this object entirely and name the module itself. The
    registry then synthesizes a definition by reading the interface callables
    off the module and its ``description`` from the module docstring summary.

    Attributes:

        name: Canonical identifier. Required by ``register``, but optional for an
            entry-point definition. The registry stamps it from the entry-point key
            so the external declaration stays the single source of truth.

        sync_pipe: Sync interface callable. Wins over ``module``'s ``pipe``.

        async_pipe: Async interface callable. Wins over ``module``'s ``async_pipe``.

        module: Object to read the interface callables off of.

        description: Summary used by module discovery. Defaults to ``module.__doc__``'s
            first non-blank line if ``module`` is given.

    """

    name: str = ""
    sync_pipe: SyncPipeCallable | None = None
    async_pipe: AsyncPipeCallable | None = None
    module: object | None = None
    description: str | None = None

    def get_pipe(self, is_async: bool = False) -> PipeCallable | Pipe | None:
        """Resolves the callable for ``interface``, or ``None`` if undefined."""
        pipe: PipeCallable | Pipe | None = (
            self.async_pipe if is_async else self.sync_pipe
        )

        if pipe is None and self.module is not None:
            interface = "async_pipe" if is_async else "pipe"
            pipe = getattr(self.module, interface, None)

        return pipe
