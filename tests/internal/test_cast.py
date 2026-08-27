# vim: sw=4:ts=4:expandtab
"""
Tests cast_datetime's try_local_tz: UTC by default, local zone when opted in.
"""

import time
from datetime import timedelta

import pytest

from riko.cast import cast_datetime


@pytest.fixture
def tokyo(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("tzset is POSIX-only")

    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    time.tzset()


class TestTryLocalTz:
    @pytest.mark.usefixtures("tokyo")
    def test_defaults_to_utc(self):
        assert cast_datetime("now").utcoffset() == timedelta(0)

    @pytest.mark.usefixtures("tokyo")
    def test_honors_local_tz(self):
        offset = cast_datetime("now", try_local_tz=True).utcoffset()
        assert offset == timedelta(hours=9)

    def test_keyword_only(self):
        with pytest.raises(TypeError):
            cast_datetime("now", False, False, True)  # pyright: ignore[reportCallIssue]
