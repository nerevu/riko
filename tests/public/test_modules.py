# vim: sw=4:ts=4:expandtab
"""
Public module-discovery contracts: filtering combinations, API errors, and the
input test-flag scoping. Exact metadata derivation lives in
``tests/internal/test_metadata.py``.
"""

import pytest

from riko.cast import CastType
from riko.context import Context
from riko.modules import describe_module, list_modules
from riko.modules.input import pipe as input_pipe
from riko.types.modules import InputConf


def test_input_test_flag_scoped_to_test_context(monkeypatch):
    """
    The auto-wired context.test skips the input prompt only in a test
    context. A non-test context (test=False) still prompts, so the flag can
    never silently suppress prompting outside of tests.
    """
    monkeypatch.setattr("builtins.input", lambda *args: "typed")
    conf = InputConf({"prompt": "?", "default": "def", "type": CastType.TEXT})

    assert next(input_pipe(conf=conf, context=Context(test=True))) == "def"
    assert next(input_pipe(conf=conf, context=Context(test=False))) == "typed"
    assert next(input_pipe(conf=conf)) == "typed"


def test_filter_non_loopable_modules():
    modules = list_modules(loopable=False, show_metadata=True)
    assert modules
    assert all(not module.loopable for module in modules)

    names = {module.name for module in modules}
    assert "input" in names
    assert "count" in names
    assert "split" in names
    assert "dateformat" not in names


def test_filter_non_loopable_sources():
    assert list_modules(subtype="source", loopable=False) == ["input"]


def test_filter_non_loopable_processors():
    assert list_modules(type="processor", loopable=False) == ["input"]


def test_type_and_subtype_cannot_be_combined():
    with pytest.raises(ValueError, match="type and subtype cannot be combined"):
        list_modules(type="operator", subtype="composer")


def test_primary_requires_subtype():
    with pytest.raises(ValueError, match="primary=True requires subtype"):
        list_modules(primary=True)


def test_describe_module_reraises_nested_dependency_error(monkeypatch):
    def boom(target):
        raise ModuleNotFoundError("No module named 'phantom_dep'", name="phantom_dep")

    monkeypatch.setattr("riko._importutils.import_module", boom)

    with pytest.raises(ModuleNotFoundError, match="phantom_dep"):
        describe_module("hash")
