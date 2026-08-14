import pytest

from riko._pubsub import reset_pubsub
from riko.bado import issync
from riko.ext.pipelines import pipeline_resolver
from riko.parsers import IS_LXML
from riko.paths import ROOT_DIR

PIPELINE_DIR = ROOT_DIR / "tests" / "pipelines"

# The core compiler ships no named-pipeline locations; the suite supplies its
# own generated-package + JSON-definition directory (formerly hardcoded as
# ``tests.pypipelines`` / ``tests/pipelines`` inside ``riko.compile``).
pipeline_resolver.configure(package="tests.pypipelines", directory=PIPELINE_DIR)


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    reset_pubsub()
    yield
    reset_pubsub()


def pytest_collection_modifyitems(items):
    skip_async = pytest.mark.skip(reason="async support not available")
    skip_lxml = pytest.mark.skip(reason="lxml not installed")

    for item in items:
        if not hasattr(item, "dtest"):
            continue

        name = item.name

        if issync and ("async" in name):
            item.add_marker(skip_async)
        elif not IS_LXML and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
