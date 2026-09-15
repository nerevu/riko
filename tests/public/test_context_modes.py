# vim: sw=4:ts=4:expandtab
"""
Execution-mode tests.

Context carries a single ExecutionMode instead of independent describe_* bools,
so contradictory inspection states are unrepresentable. The legacy bool kwargs
have been removed; describe_input/describe_dependencies remain as read-only
properties derived from the mode.
"""

from pickle import dumps, loads  # noqa: S403
from typing import cast

import pytest

from riko.context import Context, ExecutionMode

MODES = [
    (ExecutionMode.RUN, False, False),
    (ExecutionMode.DESCRIBE_INPUTS, True, False),
    (ExecutionMode.DESCRIBE_DEPENDENCIES, False, True),
    (ExecutionMode.DESCRIBE, True, True),
]


def test_default_mode_is_run():
    assert Context().mode is ExecutionMode.RUN


@pytest.mark.parametrize(("mode", "wants_input", "wants_deps"), MODES)
def test_mode_drives_describe_properties(mode, wants_input, wants_deps):
    context = Context(mode=mode)
    assert context.describe_input is wants_input
    assert context.describe_dependencies is wants_deps


def test_describe_properties_are_read_only():
    context = Context()

    with pytest.raises(AttributeError):
        context.describe_input = True  # pyright: ignore[reportAttributeAccessIssue]


def test_orthogonal_flags_preserved():
    context = Context(mode=ExecutionMode.DESCRIBE, test=True, verbose=True)
    assert context.test is True
    assert context.verbose is True
    assert context.mode is ExecutionMode.DESCRIBE


class TestContextImmutability:
    """A Context is an immutable definition-layer snapshot."""

    def test_fields_cannot_be_reassigned(self):
        context = Context()

        with pytest.raises(AttributeError):
            context.mode = ExecutionMode.DESCRIBE  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            context.verbose = True  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            context.submodule = True  # pyright: ignore[reportAttributeAccessIssue]

    def test_inputs_mapping_is_read_only(self):
        context = Context(inputs={"count": 2})

        with pytest.raises(TypeError):
            context.inputs["count"] = 3  # pyright: ignore[reportIndexIssue]

    def test_resources_mapping_is_read_only(self):
        context = Context()

        with pytest.raises(TypeError):
            context.resources["db"] = object()  # pyright: ignore[reportIndexIssue]

    def test_augment_returns_independent_snapshot(self):
        base = Context(inputs={"count": 2}, verbose=False)
        derived = base.augment(verbose=True, inputs={"limit": 5})

        assert derived is not base
        assert base.verbose is False
        assert derived.verbose is True
        assert dict(base.inputs) == {"count": 2}
        assert dict(derived.inputs) == {"limit": 5}

    def test_augment_source_mutation_does_not_leak(self):
        source = {"count": 2}
        context = Context(inputs=source)
        source["count"] = 99
        assert context.inputs["count"] == 2

    def test_roundtrips_through_pickle(self):
        context = Context(mode=ExecutionMode.DESCRIBE, inputs={"count": 2}, test=True)
        restored = cast(Context, loads(dumps(context)))  # noqa: S301

        assert restored.mode is ExecutionMode.DESCRIBE
        assert restored.test is True
        assert dict(restored.inputs) == {"count": 2}

        with pytest.raises(AttributeError):
            restored.mode = ExecutionMode.RUN  # pyright: ignore[reportAttributeAccessIssue]
