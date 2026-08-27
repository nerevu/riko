# vim: sw=4:ts=4:expandtab
"""
Tests for the P8 module registry + pipe-resolution façade (slice 1).
"""

import sys
from types import SimpleNamespace

import pytest

from riko.collections import SyncPipe
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.ext import register
from riko.ext._pipelines import (
    CompositeStore,
    DirectoryStore,
    MappingStore,
    PackageStore,
    PipelineResolver,
    pipeline_resolver,
)
from riko.ext._resolver import PipeResolver, pipe_resolver
from riko.ext.registry import ModuleDefinition, registry, reset_registry
from riko.modules import list_modules, tokenizer
from riko.paths import ROOT_DIR

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

    def test_missing_dotted_module_raises_unsupported(self, clean_registry):
        # a dotted name fails to import at its missing parent package, not the
        # full target; the guard must still map that to UnsupportedModuleError
        with pytest.raises(UnsupportedModuleError):
            clean_registry.resolve("acme.does_not_exist", "pipe")

    def test_transitive_import_error_preserved(self, clean_registry, monkeypatch):
        """
        A missing dep *inside* a real module surfaces as ModuleNotFoundError,
        not UnsupportedModuleError.
        """

        def fake_import(name, *args, **kwargs):
            if name == "riko.modules.tokenizer":
                raise ModuleNotFoundError("No module named 'ghost'", name="ghost")

            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("riko._importutils.import_module", fake_import)

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


class TestPublicRegister:
    """The public ``riko.ext.register`` surface, targeting the global registry."""

    def test_register_resolves_via_facade(self, clean_registry):
        register(ModuleDefinition(name="acme.echo", sync_pipe=marker))
        assert pipe_resolver.resolve("acme.echo", "pipe") is marker
        assert registry.resolve("acme.echo", "pipe") is marker

    def test_register_runs_end_to_end(self, clean_registry):
        # a registered alias of a built-in resolves and runs through SyncPipe
        register(ModuleDefinition(name="acme.tok", module=tokenizer))
        flow = SyncPipe(
            "acme.tok", source=[{"content": "a b c"}], conf={"delimiter": " "}
        )
        assert [item.get("content") for item in flow] == ["a", "b", "c"]

    def test_register_requires_name(self, clean_registry):
        with pytest.raises(ValueError, match="needs a name"):
            register(ModuleDefinition(sync_pipe=marker))

    def test_reset_registry_clears_registration(self, clean_registry):
        register(ModuleDefinition(name="acme.echo", sync_pipe=marker))
        reset_registry()

        with pytest.raises(UnsupportedModuleError):
            pipe_resolver.resolve("acme.echo", "pipe")


class TestPipeResolver:
    def test_module_resolves_via_registry(self, clean_registry):
        assert pipe_resolver.resolve("tokenizer", "pipe").__name__ == "pipe"

    def test_pipeline_delegates_to_compiler(self, clean_registry):
        with pytest.raises(UnsupportedModuleError):
            # non-pipe_ missing name goes through the registry
            pipe_resolver.resolve("nope", "pipe")

    def test_runtime_pipe_resolution_imports_no_compiler(self, clean_registry):
        """Resolving an ordinary module must not pull in riko.compile."""
        sys.modules.pop("riko.compile", None)
        PipeResolver(clean_registry, pipeline_resolver).resolve("tokenizer", "pipe")
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
        assert pipe_resolver.resolve("acme.hello", "pipe") is marker

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
        # a bare (unconfigured) resolver finds no pipe_* module and no definition
        resolver = PipelineResolver()
        assert resolver.load("pipe_x") is None

        with pytest.raises(UnsupportedPipelineError):
            resolver.load_definition("pipe_x")

    def test_configured_resolver_imports_generated_module(self):
        resolver = PipelineResolver(store=PackageStore("tests.pypipelines"))
        assert resolver.load("pipe_kazeeki1") is not None

    def test_missing_module_returns_none(self):
        resolver = PipelineResolver(store=PackageStore("tests.pypipelines"))
        assert resolver.load("pipe_missing") is None

    def test_directory_store_compiles_definition(self):
        directory = ROOT_DIR / "tests" / "pipelines"
        resolver = PipelineResolver(definitions=DirectoryStore(directory))
        assert "modules" in resolver.load_definition("pipe_gigs")

        with pytest.raises(UnsupportedPipelineError):
            resolver.load_definition("pipe_missing")

    def test_composite_store_first_hit_wins(self):
        store = CompositeStore(
            MappingStore({}),
            MappingStore({"pipe_x": tokenizer}),
            PackageStore("tests.pypipelines"),
        )
        assert store.load("pipe_x") is tokenizer
        assert store.load("absent") is None

    def test_mapping_store_serves_in_memory_module(self):
        resolver = PipelineResolver(store=MappingStore({"pipe_mem": tokenizer}))
        assert resolver.load("pipe_mem") is tokenizer


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
