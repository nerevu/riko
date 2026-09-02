# vim: sw=4:ts=4:expandtab
"""Tests the sink write-mode contract (``riko.sinks``)."""

from dataclasses import FrozenInstanceError

import pytest

from riko.sinks import SinkMode, sink_write


def test_mode_values():
    assert [m.value for m in SinkMode] == ["append", "merge", "replace", "delete"]


@pytest.mark.parametrize(
    ("mode", "keyed"),
    [
        (SinkMode.APPEND, False),
        (SinkMode.MERGE, True),
        (SinkMode.REPLACE, True),
        (SinkMode.DELETE, True),
    ],
)
def test_keyed_classification(mode, keyed):
    assert mode.keyed is keyed


@pytest.mark.parametrize(
    ("mode", "destructive"),
    [
        (SinkMode.APPEND, False),
        (SinkMode.MERGE, False),
        (SinkMode.REPLACE, True),
        (SinkMode.DELETE, True),
    ],
)
def test_destructive_classification(mode, destructive):
    assert mode.destructive is destructive


def test_merge_requires_keys_and_normalizes_string():
    spec = sink_write("merge", keys="endpoint_id")

    assert spec.mode is SinkMode.MERGE
    assert spec.keys == ("endpoint_id",)
    assert spec.idempotency_key == ()


def test_keyed_modes_normalize_iterable_keys():
    spec = sink_write("delete", keys=["serial", "hostname"])
    assert spec.keys == ("serial", "hostname")


def test_append_accepts_idempotency_key():
    spec = sink_write(
        "append", idempotency_key=("report_month", "endpoint_id", "update_id")
    )

    assert spec.mode is SinkMode.APPEND
    assert spec.keys == ()
    assert spec.idempotency_key == ("report_month", "endpoint_id", "update_id")


def test_append_without_idempotency_key_is_allowed():
    assert sink_write("append").idempotency_key == ()


def test_keyed_mode_missing_keys_is_rejected():
    with pytest.raises(ValueError, match="requires 'keys'"):
        sink_write("merge")


def test_keyed_mode_rejects_idempotency_key():
    with pytest.raises(ValueError, match="forbids 'idempotency_key'"):
        sink_write("merge", keys="id", idempotency_key="id")


def test_append_rejects_keys():
    with pytest.raises(ValueError, match="forbids 'keys'"):
        sink_write("append", keys="id")


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="upsert"):
        sink_write("upsert", keys="id")


def test_sink_write_is_frozen():
    spec = sink_write("merge", keys="id")

    with pytest.raises(FrozenInstanceError):
        spec.mode = SinkMode.DELETE  # pyright: ignore[reportAttributeAccessIssue]
