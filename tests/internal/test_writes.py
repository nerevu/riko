# vim: sw=4:ts=4:expandtab
"""Tests the declarative write model (``riko.types._write``)."""

from dataclasses import FrozenInstanceError

import pytest

from riko.types._write import Formats, WriteCapabilities, WriteMode, WriteOperation


def test_mode_values():
    assert [m.value for m in WriteMode] == ["append", "merge", "replace", "delete"]


def test_format_values():
    assert [f.value for f in Formats] == [
        "csv",
        "geojson",
        "json",
        "jsonl",
        "ofx",
        "qif",
    ]


class TestWriteOperation:
    def test_is_plain_normalized_intent(self):
        op = WriteOperation(WriteMode.MERGE, keys=("endpoint_id",))

        assert op.mode is WriteMode.MERGE
        assert op.keys == ("endpoint_id",)

    def test_keys_default_empty(self):
        assert WriteOperation(WriteMode.APPEND).keys == ()

    def test_is_frozen(self):
        op = WriteOperation(WriteMode.REPLACE)

        with pytest.raises(FrozenInstanceError):
            op.mode = WriteMode.APPEND  # pyright: ignore[reportAttributeAccessIssue]


class TestWriteCapabilities:
    def test_appendable_derived_from_modes(self):
        appendable = WriteCapabilities(modes=frozenset({WriteMode.APPEND}))
        unappendable = WriteCapabilities(modes=frozenset({WriteMode.REPLACE}))

        assert appendable.appendable is True
        assert unappendable.appendable is False

    def test_serializes_derived_from_format(self):
        serializing = WriteCapabilities(modes=frozenset(), fmt=Formats.CSV)
        native = WriteCapabilities(modes=frozenset())

        assert serializing.serializes is True
        assert native.serializes is False

    def test_keyed_modes_is_union(self):
        caps = WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )

        assert caps.keyed_modes == frozenset({WriteMode.MERGE, WriteMode.APPEND})

    def test_keyed_modes_must_be_subset_of_modes(self):
        with pytest.raises(ValueError, match="not present in modes"):
            WriteCapabilities(
                modes=frozenset({WriteMode.REPLACE}),
                match_keyed_modes=frozenset({WriteMode.MERGE}),
            )

    def test_match_and_idempotent_must_not_overlap(self):
        with pytest.raises(ValueError, match="must not overlap"):
            WriteCapabilities(
                modes=frozenset({WriteMode.MERGE}),
                match_keyed_modes=frozenset({WriteMode.MERGE}),
                idempotent_modes=frozenset({WriteMode.MERGE}),
            )
