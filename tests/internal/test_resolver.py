# vim: sw=4:ts=4:expandtab
"""
Tests for the P8 module registry + stage-resolution façade (slice 1).
"""

import sys
from types import SimpleNamespace

import pytest

from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.ext.pipelines import PipelineResolver
from riko.ext.registry import ModuleDefinition, registry
from riko.ext.resolver import StageResolver, stage_resolver
from riko.modules import list_modules

_META = {
    "type": "operator",
    "subtype": "composer",
    "subtypes": {"composer"},
    "pollable": False,
    "loopable": False,
    "isasync": False,
}

_NAME = "acme.mod"


@pytest.fixture
def clean_registry():
    registry.reset()
    yield registry
    registry.reset()


marker = lambda source, **_: source


def _patch_entry_points(monkeypatch, *eps):
    ep_func = lambda group: list(eps) if group == "riko.modules" else []
    monkeypatch.setattr("riko.ext.registry.entry_points", ep_func)


def _pipe_wrapper(**attrs):
    wrapper = lambda source, **_: source
    for key, value in attrs.items():
        setattr(wrapper, key, value)

    return wrapper


class _FakeEntryPoint:
    def __init__(self, name, definition):
        self.name = name
        self._definition = definition

    def load(self):
        return self._definition


class TestModuleRegistry:
    def test_builtin_resolves_lazily(self, clean_registry):
        assert clean_registry.resolve("tokenizer", "pipe").__name__ == "pipe"

    def test_missing_module_raises_unsupported(self, clean_registry):
        with pytest.raises(UnsupportedModuleError):
            clean_registry.resolve("does_not_exist", "pipe")

    def test_transitive_import_error_preserved(self, clean_registry, monkeypatch):
        """
        A missing dep *inside* a real module surfaces as ModuleNotFoundError,
        not UnsupportedModuleError.
        """

        def fake_import(name, *args, **kwargs):
            if name == "riko.modules.tokenizer":
                raise ModuleNotFoundError("No module named 'ghost'", name="ghost")

            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("riko.ext.registry.import_module", fake_import)

        with pytest.raises(ModuleNotFoundError) as e:
            clean_registry.resolve("tokenizer", "pipe")

        assert not isinstance(e.value, UnsupportedModuleError)

    def test_runtime_registration_takes_precedence(self, clean_registry):
        clean_registry.register(ModuleDefinition(name="tokenizer", sync_pipe=marker))
        assert clean_registry.resolve("tokenizer", "pipe") is marker

    def test_register_rejects_duplicate_without_replace(self, clean_registry):
        defn = ModuleDefinition(name="mymod", sync_pipe=marker)
        clean_registry.register(defn)

        with pytest.raises(ValueError, match="already registered"):
            clean_registry.register(defn)

        clean_registry.register(defn, replace=True)

    def test_registered_module_missing_interface_raises(self, clean_registry):
        clean_registry.register(ModuleDefinition(name="synconly", sync_pipe=marker))

        with pytest.raises(UnsupportedModuleError):
            clean_registry.resolve("synconly", "async_pipe")

    def test_runtime_register_requires_name(self, clean_registry):
        with pytest.raises(ValueError, match="needs a name"):
            clean_registry.register(ModuleDefinition(sync_pipe=marker))

    def test_module_convention_derives_both_interfaces(self, clean_registry):
        mod = SimpleNamespace(pipe=marker, async_pipe=marker)
        clean_registry.register(ModuleDefinition(name=_NAME, module=mod))

        assert clean_registry.resolve(_NAME, "pipe") is marker
        assert clean_registry.resolve(_NAME, "async_pipe") is marker

    def test_explicit_callable_overrides_module(self, clean_registry):
        other = lambda source, **_: source
        mod = SimpleNamespace(pipe=other, async_pipe=other)
        definition = ModuleDefinition(name=_NAME, sync_pipe=marker, module=mod)
        clean_registry.register(definition)

        assert clean_registry.resolve(_NAME, "pipe") is marker  # explicit wins
        assert clean_registry.resolve(_NAME, "async_pipe") is other  # from module


class TestStageResolver:
    def test_module_resolves_via_registry(self, clean_registry):
        assert stage_resolver.resolve("tokenizer", "pipe").__name__ == "pipe"

    def test_pipeline_delegates_to_compiler(self, clean_registry):
        with pytest.raises(UnsupportedModuleError):
            # non-pipe_ missing name goes through the registry
            stage_resolver.resolve("nope", "pipe")

    def test_runtime_stage_resolution_imports_no_compiler(self, clean_registry):
        """Resolving an ordinary module must not pull in riko.compile."""
        sys.modules.pop("riko.compile", None)
        StageResolver(clean_registry).resolve("tokenizer", "pipe")
        assert "riko.compile" not in sys.modules


class TestEntryPointModules:
    """DoD #1: an external package supplies modules via entry points, no core edit."""

    def test_entry_point_module_resolves(self, monkeypatch, clean_registry):
        defn = ModuleDefinition(name="acme.hello", sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint("acme.hello", defn))
        clean_registry.reset()
        assert clean_registry.resolve("acme.hello", "pipe") is marker

    def test_name_stamped_from_entry_point_key(self, monkeypatch, clean_registry):
        # definition omits name — the registry adopts the entry-point key
        defn = ModuleDefinition(sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint("acme.hello", defn))
        clean_registry.reset()

        assert clean_registry.resolve("acme.hello", "pipe") is marker
        assert clean_registry._entry_point_definition("acme.hello").name == "acme.hello"

    def test_name_key_mismatch_raises(self, monkeypatch, clean_registry):
        defn = ModuleDefinition(name="acme.other", sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint("acme.hello", defn))
        clean_registry.reset()

        with pytest.raises(ValueError, match="must match"):
            clean_registry.resolve("acme.hello", "pipe")

    def test_entry_point_via_facade(self, monkeypatch, clean_registry):
        defn = ModuleDefinition(name="acme.hello", sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint("acme.hello", defn))
        clean_registry.reset()
        assert stage_resolver.resolve("acme.hello", "pipe") is marker

    def test_runtime_registration_shadows_entry_point(
        self, monkeypatch, clean_registry
    ):
        definition = ModuleDefinition("acme.hello", marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint("acme.hello", definition))
        clean_registry.reset()
        clean_registry.register(ModuleDefinition("acme.hello", marker))
        assert clean_registry.resolve("acme.hello", "pipe") is marker

    def test_entry_points_discovered_lazily_once(self, monkeypatch, clean_registry):
        calls = {"n": 0}

        def counting(group):
            calls["n"] += 1
            return []

        monkeypatch.setattr("riko.ext.registry.entry_points", counting)
        clean_registry.reset()

        with pytest.raises(UnsupportedModuleError):
            clean_registry.resolve("nope", "pipe")

        with pytest.raises(UnsupportedModuleError):
            clean_registry.resolve("nope", "pipe")

        assert calls["n"] == 1


class TestPipelineResolver:
    def test_core_default_has_no_named_pipelines(self):
        """
        A bare (unconfigured) resolver resolves no ``pipe_*`` — core ships
        no named-pipeline locations.
        """
        with pytest.raises(UnsupportedPipelineError):
            PipelineResolver().load("pipe_x", "pipe_x")

    def test_configured_resolver_imports_generated_module(self):
        resolver = PipelineResolver(package="tests.pypipelines")
        module, parsed = resolver.load("pipe_kazeeki1", "pipe_kazeeki1")
        assert module is not None
        assert parsed is None

    def test_missing_pipeline_raises_unsupported(self):
        resolver = PipelineResolver(package="tests.pypipelines")

        with pytest.raises(UnsupportedPipelineError):
            resolver.load("pipe_missing", "pipe_missing")


class TestCatalog:
    def test_registered_module_appears_in_catalog(self, clean_registry):
        pipe = _pipe_wrapper(name=_NAME, **_META)
        clean_registry.register(ModuleDefinition(name=_NAME, sync_pipe=pipe))

        assert _NAME in list_modules()
        assert "tokenizer" in list_modules()  # built-ins still present

    def test_bare_callable_skipped_in_catalog(self, clean_registry):
        # resolvable but carries no metadata → listed nowhere, and no error
        clean_registry.register(ModuleDefinition(name="acme.bare", sync_pipe=marker))

        assert "acme.bare" not in list_modules()
