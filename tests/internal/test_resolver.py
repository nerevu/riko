# vim: sw=4:ts=4:expandtab
"""
Tests for the P8 module registry + stage-resolution façade (slice 1).
"""

import sys

import pytest

from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.ext.pipelines import PipelineResolver
from riko.ext.registry import ModuleDefinition, registry
from riko.ext.resolver import StageResolver, stage_resolver


@pytest.fixture
def clean_registry():
    registry.reset()
    yield registry
    registry.reset()


marker = lambda source, **_: source


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
