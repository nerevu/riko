import pytest

from riko._pubsub import reset_pubsub


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    reset_pubsub()
    yield
    reset_pubsub()
