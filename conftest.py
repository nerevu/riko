import pytest

from riko.bado import issync
from riko.parsers import IS_LXML
from riko.utils import reset_pubsub


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    reset_pubsub()
    yield
    reset_pubsub()


_TWISTED_ONLY_DOCTESTS = {
    "riko.bado.itertools.ensure_deferred",
    "riko.bado.mock.FakeReactor",
}


def pytest_collection_modifyitems(items):
    skip_async = pytest.mark.skip(reason="async support not available")
    skip_lxml = pytest.mark.skip(reason="lxml not installed")

    for item in items:
        if not hasattr(item, "dtest"):
            continue

        name = item.name

        if issync and ("async" in name or name in _TWISTED_ONLY_DOCTESTS):
            item.add_marker(skip_async)
        elif not IS_LXML and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
