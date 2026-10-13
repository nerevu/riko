# vim: sw=4:ts=4:expandtab
"""Tests documented date coercion forms and timezone normalization."""

import time
from datetime import datetime, timedelta, tzinfo

import pytest
from dateutil.relativedelta import relativedelta

from riko.coercion._dates import resolve_aware_datetime
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


class NamelessZone(tzinfo):
    def tzname(self, dt: datetime | None) -> None:
        return None

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)


def test_resolve_aware_datetime_keeps_a_nameless_zone():
    zone = NamelessZone()
    result = resolve_aware_datetime(
        datetime(2020, 1, 1, tzinfo=zone), try_local_tz=False
    )
    assert isinstance(result, datetime)
    assert result.tzinfo is zone


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

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the settable date timezone work: with try_local_tz, named "
        "days ('now') use the local zone but counted offsets ('+1 seconds') stay UTC",
    )
    @pytest.mark.usefixtures("tokyo")
    def test_relative_offsets_share_the_named_day_zone(self):
        named = cast_datetime("now", try_local_tz=True)
        offset = cast_datetime("+1 seconds", try_local_tz=True)
        assert named is not None
        assert offset is not None
        assert offset.utcoffset() == named.utcoffset()

    def test_keyword_only(self):
        with pytest.raises(TypeError):
            cast_datetime("now", False, False, True)  # pyright: ignore[reportCallIssue]
