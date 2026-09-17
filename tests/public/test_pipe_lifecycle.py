# vim: sw=4:ts=4:expandtab
"""Shared one-shot lifecycle contract for sync and async pipes."""

import pytest

from riko.base._paths import get_path
from riko.base.exceptions import PipelineStateError
from riko.runtime.collections import PipeState, SyncCollection
from tests import skipif_issync
from tests._lifecycle import AsyncLifecycleBackend, SyncLifecycleBackend

BACKENDS = [
    pytest.param(SyncLifecycleBackend(), id="sync"),
    pytest.param(AsyncLifecycleBackend(), marks=skipif_issync, id="async"),
]


@pytest.mark.parametrize("backend", BACKENDS)
class TestLifecycleContract:
    def test_new_state(self, backend):
        assert backend.new_pipe().state is PipeState.NEW

    def test_exhausted_after_full_iteration(self, backend):
        flow = backend.stream_pipe()
        assert len(backend.consume(flow)) == backend.stream_count
        assert flow.exhausted
        assert flow.state is PipeState.EXHAUSTED

    def test_exhausted_reiterates_empty_without_reexecution(self, backend):
        flow = backend.stream_pipe()
        first = backend.consume(flow)
        second = backend.consume(flow)
        assert len(first) == backend.stream_count
        assert second == []

    def test_chain_while_new_is_allowed(self, backend):
        chained = backend.chainable_pipe().hash()
        assert chained.state is PipeState.NEW

    def test_chain_after_partial_iteration_wraps_remainder(self, backend):
        flow = backend.stream_pipe()
        state, result = backend.partial_then_count(flow)
        assert state is PipeState.RUNNING
        assert result == [{"count": backend.remaining_count}]

    def test_chain_after_exhaustion_is_allowed(self, backend):
        flow = backend.stream_pipe()
        backend.consume(flow)
        assert backend.consume(flow.count()) == [{"count": 0}]

    def test_close_is_idempotent(self, backend):
        flow = backend.new_pipe()
        backend.close(flow)
        backend.close(flow)
        assert flow.closed
        assert flow.state is PipeState.CLOSED

    def test_chain_after_close_raises(self, backend):
        flow = backend.new_pipe()
        backend.close(flow)

        with pytest.raises(PipelineStateError):
            flow.count()

    def test_chain_after_failure_raises(self, backend):
        flow = backend.failing_pipe()

        with pytest.raises(RuntimeError):
            backend.consume(flow)

        with pytest.raises(PipelineStateError):
            flow.count()

    def test_iterate_after_run_then_close_is_empty(self, backend):
        flow = backend.stream_pipe()
        assert len(backend.consume(flow)) == backend.stream_count
        backend.close(flow)
        assert backend.consume(flow) == []

    def test_close_before_iteration_does_not_execute(self, backend):
        ran: list[int] = []
        flow = backend.lazy_pipe(ran)
        backend.close(flow)
        assert backend.consume(flow) == []
        assert ran == []

    def test_collection_close_before_iteration_does_not_execute(self, backend):
        ran: list[int] = []

        def sources():
            ran.append(1)
            yield {"url": get_path("feed.xml")}

        stream = backend.collection(sources())
        backend.close(stream)
        assert backend.consume(stream) == []
        assert ran == []

    def test_failed_state_reiterates_empty(self, backend):
        flow = backend.failing_pipe()

        with pytest.raises(RuntimeError):
            backend.consume(flow)

        assert flow.state is PipeState.FAILED
        assert flow.failed
        assert backend.consume(flow) == []

    def test_context_manager_closes(self, backend):
        flow = backend.context_pipe()
        items = backend.context_consume(flow)

        assert items
        if backend.context_count is not None:
            assert len(items) == backend.context_count
        assert flow.closed
        assert flow.state is PipeState.CLOSED

    def test_collection_lifecycle(self, backend):
        stream = backend.collection([{"url": get_path("feed.xml")}])
        assert stream.state is PipeState.NEW
        assert backend.consume(stream)
        assert stream.exhausted
        assert backend.consume(stream) == []

    def test_collection_close_is_idempotent(self, backend):
        stream = backend.collection([{"url": get_path("feed.xml")}])
        backend.close(stream)
        backend.close(stream)
        assert stream.closed
        assert stream.state is PipeState.CLOSED


class TestSyncLifecycle:
    def test_collection_failed_state(self):
        def boom_sources():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        stream = SyncCollection(boom_sources())

        try:
            list(stream)
        except RuntimeError:
            pass

        assert stream.state is PipeState.FAILED
        assert stream.failed
        assert list(stream) == []
