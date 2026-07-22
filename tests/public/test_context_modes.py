# vim: sw=4:ts=4:expandtab
"""
Execution-mode tests for the Phase 6 contract (docs/P6_CHECKLIST.md).

Context carries a single ExecutionMode instead of independent describe_* bools,
so contradictory inspection states are unrepresentable. Legacy bool kwargs are
still accepted and translated; describe_input/describe_dependencies remain as
read-only compatibility properties derived from the mode.
"""

import pytest

from riko import Context, ExecutionMode

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


def test_legacy_describe_input_kwarg():
    context = Context(describe_input=True)
    assert context.mode is ExecutionMode.DESCRIBE_INPUTS
    assert context.describe_input is True


def test_legacy_describe_dependencies_kwarg():
    context = Context(describe_dependencies=True)
    assert context.mode is ExecutionMode.DESCRIBE_DEPENDENCIES


def test_legacy_both_kwargs_is_describe():
    context = Context(describe_input=True, describe_dependencies=True)
    assert context.mode is ExecutionMode.DESCRIBE
    assert context.describe_input is True
    assert context.describe_dependencies is True


def test_describe_properties_are_read_only():
    context = Context()

    with pytest.raises(AttributeError):
        context.describe_input = True


def test_orthogonal_flags_preserved():
    context = Context(mode=ExecutionMode.DESCRIBE, test=True, verbose=True)
    assert context.test is True
    assert context.verbose is True
    assert context.mode is ExecutionMode.DESCRIBE
