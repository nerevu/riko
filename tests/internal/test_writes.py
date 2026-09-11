# vim: sw=4:ts=4:expandtab
"""Tests the write-mode contract (``riko.writes``)."""

from dataclasses import FrozenInstanceError

import pytest

from riko.types._write import WriteMode, WriteOperation


def test_mode_values():
    assert [m.value for m in WriteMode] == ["append", "merge", "replace", "delete"]


@pytest.mark.parametrize(
    ("mode", "keyed"),
    [
        (WriteMode.APPEND, False),
        (WriteMode.MERGE, True),
        (WriteMode.REPLACE, True),
        (WriteMode.DELETE, True),
    ],
)
def test_keyed_classification(mode, keyed):
    assert mode.keyed is keyed


@pytest.mark.parametrize(
    ("mode", "destructive"),
    [
        (WriteMode.APPEND, False),
        (WriteMode.MERGE, False),
        (WriteMode.REPLACE, True),
        (WriteMode.DELETE, True),
    ],
)
def test_destructive_classification(mode, destructive):
    assert mode.destructive is destructive


def test_merge_requires_keys_and_normalizes_string():
    spec = WriteOperation("merge", keys="endpoint_id")

    assert spec.mode is WriteMode.MERGE
    assert spec.keys == ("endpoint_id",)


def test_keyed_modes_normalize_iterable_keys():
    spec = WriteOperation("delete", keys=["serial", "hostname"])
    assert spec.keys == ("serial", "hostname")


def test_append_accepts_idempotency_key():
    spec = WriteOperation("append", keys=("report_month", "endpoint_id", "update_id"))

    assert spec.mode is WriteMode.APPEND
    assert spec.keys == ()


def test_append_without_idempotency_key_is_allowed():
    assert WriteOperation("append").keys == ()


def test_keyed_mode_missing_keys_is_rejected():
    with pytest.raises(ValueError, match="requires 'keys'"):
        WriteOperation("merge")


def test_append_rejects_keys():
    with pytest.raises(ValueError, match="forbids 'keys'"):
        WriteOperation("append", keys="id")


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="upsert"):
        WriteOperation("upsert", keys="id")


def test_write_operation_is_frozen():
    spec = WriteOperation("merge", keys="id")

    with pytest.raises(FrozenInstanceError):
        spec.mode = WriteMode.DELETE  # pyright: ignore[reportAttributeAccessIssue]
