# vim: sw=4:ts=4:expandtab
"""Tests documented date coercion forms and timezone normalization."""

import time
from datetime import timedelta

import pytest
from dateutil.relativedelta import relativedelta

from riko.coercion.cast import cast_datetime


@pytest.fixture
def tokyo(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("tzset is POSIX-only")

    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    time.tzset()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Jan. 12, 2001", (2001, 1, 12)),
        ("10/21/1958", (1958, 10, 21)),
        ("15 JUN 06", (2006, 6, 15)),
    ],
)
def test_documented_absolute_date_strings(value, expected):
    result = cast_datetime(value)
    assert result is not None
    assert (result.year, result.month, result.day) == expected


def test_documented_relative_date_strings():
    today = cast_datetime("today")
    assert today is not None
    assert cast_datetime("+3 days") == today + timedelta(days=3)
    assert cast_datetime("-10 weeks") == today - timedelta(weeks=10)
    assert cast_datetime("last year") == today - relativedelta(years=1)


def test_documented_epoch_value():
    result = cast_datetime(1181230100)
    assert result is not None
    assert int(result.timestamp()) == 1181230100


class TestTryLocalTz:
    @pytest.mark.usefixtures("tokyo")
    def test_defaults_to_utc(self):
        if dt := cast_datetime("now"):
            offset = dt.utcoffset()
        else:
            offset = None

        assert offset == timedelta(0)

    @pytest.mark.usefixtures("tokyo")
    def test_honors_local_tz(self):
        if dt := cast_datetime("now", try_local_tz=True):
            offset = dt.utcoffset()
        else:
            offset = None

        assert offset == timedelta(hours=9)

    def test_keyword_only(self):
        with pytest.raises(TypeError):
            cast_datetime("now", False, False, True)  # pyright: ignore[reportCallIssue]
