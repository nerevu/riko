# vim: sw=4:ts=4:expandtab
"""Backend mechanics for the shared pipe lifecycle contract tests."""

from typing import Any

from riko.bado._backend import run
from riko.runtime.collections import (
    AsyncCollection,
    AsyncPipe,
    SyncCollection,
    SyncPipe,
)
from riko.types.modules import ItemBuilderConf

BUILDER_CONF = ItemBuilderConf({"attrs": [{"key": "content", "value": "a,b,c"}]})
SRC = [{"content": "x"}, {"content": "y"}]


class SyncLifecycleBackend:
    """Adapt sync pipe mechanics to the shared lifecycle contract."""

    stream_count = 2
    remaining_count = 1
    context_count = 2

    def new_pipe(self):
        return SyncPipe("hash", source=SRC)

    def stream_pipe(self):
        return SyncPipe("hash", source=SRC)

    def chainable_pipe(self):
        return SyncPipe("itembuilder", conf=BUILDER_CONF)

    def failing_pipe(self):
        def boom():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        return SyncPipe("hash", source=boom())

    def lazy_pipe(self, ran: list[int]):
        def source():
            ran.append(1)
            yield {"content": "x"}

        return SyncPipe("hash", source=source())

    def context_pipe(self):
        return SyncPipe("hash", source=SRC)

    def collection(self, source: Any):
        return SyncCollection(source)

    def consume(self, stream: Any) -> list[Any]:
        return list(stream)

    def partial_then_count(self, flow: Any) -> tuple[Any, list[Any]]:
        next(flow)
        return flow.state, list(flow.count())

    def close(self, stream: Any) -> None:
        stream.close()

    def context_consume(self, pipe: Any) -> list[Any]:
        with pipe:
            return list(pipe)


class AsyncLifecycleBackend:
    """Adapt async pipe mechanics to the shared lifecycle contract."""

    stream_count = 3
    remaining_count = 2
    context_count = None

    def new_pipe(self):
        return AsyncPipe("itembuilder", conf=BUILDER_CONF)

    def stream_pipe(self):
        return AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)

    def chainable_pipe(self):
        return AsyncPipe("itembuilder", conf=BUILDER_CONF)

    def failing_pipe(self):
        async def boom():
            raise RuntimeError("boom")

        return AsyncPipe(source=boom())

    def lazy_pipe(self, ran: list[int]):
        async def source():
            ran.append(1)
            yield {"content": "x"}

        return AsyncPipe("hash", source=source())

    def context_pipe(self):
        return AsyncPipe("itembuilder", conf=BUILDER_CONF)

    def collection(self, source: Any):
        return AsyncCollection(source)

    def consume(self, stream: Any) -> list[Any]:
        async def collect() -> list[Any]:
            return [item async for item in stream]

        return run(collect)

    def partial_then_count(self, flow: Any) -> tuple[Any, list[Any]]:
        async def run_case() -> tuple[Any, list[Any]]:
            await anext(flow)
            state = flow.state
            result = [item async for item in flow.count()]
            return state, result

        return run(run_case)

    def close(self, stream: Any) -> None:
        async def close_stream() -> None:
            await stream.aclose()

        run(close_stream)

    def context_consume(self, pipe: Any) -> list[Any]:
        async def collect() -> list[Any]:
            async with pipe:
                return [item async for item in pipe]

        return run(collect)
