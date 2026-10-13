# vim: sw=4:ts=4:expandtab
"""Tests that the shared ``require_*`` guards raise the error their caller picks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._targets import build_write
from riko.definitions._write import WriteMode
from riko.types._collections import (
    require_binding,
    require_finite,
    require_from_attrs,
    require_str,
    require_strlike,
)
from riko.types._enums import Executor, resolve_enum
from riko.types._guards import require_mapping, require_sequence
from riko.types._workflow import Endpoint

if TYPE_CHECKING:
    from collections.abc import Callable

_INVALID: list[tuple[Callable[..., object], object]] = [
    (require_str, 1),
    (require_strlike, 1),
    (require_finite, float("nan")),
    (require_mapping, "abc"),
    (require_sequence, "abc"),
]


@pytest.mark.parametrize(("require", "value"), _INVALID)
def test_document_error_is_the_default(require, value):
    with pytest.raises(InvalidPipelineError, match="field"):
        require(value, "field")


@pytest.mark.parametrize(("require", "value"), [*_INVALID, (require_binding, 1)])
def test_caller_can_pick_the_error(require, value):
    with pytest.raises(ValueError, match="field"):
        require(value, "field", error=ValueError)


@pytest.mark.parametrize("value", [None, "bogus"])
def test_resolve_enum_defaults_to_the_document_error(value):
    with pytest.raises(InvalidPipelineError, match="WriteMode"):
        resolve_enum(WriteMode, value)


def test_resolve_enum_lists_the_accepted_values():
    with pytest.raises(ValueError, match="'bogus'") as excinfo:
        resolve_enum(Executor, "bogus", error=ValueError)

    assert all(name in str(excinfo.value) for name in Executor)


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"mode": "bogus"}, ValueError, "Invalid WriteMode: 'bogus'"),
        ({"mode": "merge", "keys": 5}, TypeError, "keys must be a string"),
        ({"mode": "merge", "keys": ["a", "a"]}, ValueError, "duplicate keys"),
    ],
)
def test_build_write_raises_call_site_errors(kwargs, error, match):
    with pytest.raises(error, match=match):
        build_write("out.csv", **kwargs)


def test_context_mode_raises_a_call_site_error():
    with pytest.raises(ValueError, match="Invalid ExecutionMode"):
        Context(mode="bogus")


def test_required_attrs_keys_respect_exclude():
    require = require_from_attrs(Endpoint, exclude={"port"})
    assert require({"node": "a"}) == {"node": "a"}

    with pytest.raises(
        InvalidPipelineError, match=r"missing Endpoint key\(s\): \['node'\]"
    ):
        require({"port": "out"})
