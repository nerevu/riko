import pytest

from riko.bado import _issync
from riko.utils import reset_pubsub

try:
    import lxml as _lxml  # noqa: F401

    _has_lxml = True
except ImportError:
    _has_lxml = False


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

        if _issync and ("async" in name or name in _TWISTED_ONLY_DOCTESTS):
            item.add_marker(skip_async)
        elif not _has_lxml and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
