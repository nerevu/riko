# vim: sw=4:ts=4:expandtab
"""Tests for reading TypedDict required and optional keys."""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import require_from_typed_dict, typed_dict_keys
from riko.types._compiler import Embed, PipeModule

if TYPE_CHECKING:
    from collections.abc import Sequence

    from riko.types._scalars import BasicValue


class Partial(TypedDict, total=False):
    kept: Required[BasicValue]
    loose: Sequence[BasicValue]


class Whole(TypedDict):
    plain: BasicValue
    dropped: NotRequired[BasicValue]
    qualified: typing.NotRequired[Sequence[BasicValue]]


class Inherited(Partial):
    added: BasicValue


def test_qualifiers_found_without_resolving_annotations():
    assert typed_dict_keys(Partial) == (frozenset({"kept"}), frozenset({"loose"}))
    assert typed_dict_keys(Whole) == (
        frozenset({"plain"}),
        frozenset({"dropped", "qualified"}),
    )


def test_inherited_keys_keep_each_class_totality():
    assert typed_dict_keys(Inherited) == (
        frozenset({"kept", "added"}),
        frozenset({"loose"}),
    )


def test_shipped_typed_dict_qualifiers_are_honored():
    assert typed_dict_keys(PipeModule)[0] == {"id", "type", "conf"}
    assert typed_dict_keys(Embed) == (frozenset({"conf", "name"}), frozenset({"id"}))


def test_required_qualifier_is_enforced():
    require = require_from_typed_dict(PipeModule)

    with pytest.raises(
        InvalidPipelineError, match=r"missing PipeModule key\(s\): \['conf'\]"
    ):
        require({"id": "a", "type": "fetch"})
