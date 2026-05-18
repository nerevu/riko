import pytest
from riko.utils import _registry, _receive_queue


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    _registry.clear()
    _receive_queue.clear()
    yield
    _registry.clear()
    _receive_queue.clear()
