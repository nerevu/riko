import pytest

from riko.utils import _receive_queue, _registry


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    _registry.clear()
    _receive_queue.clear()
    yield
    _registry.clear()
    _receive_queue.clear()
