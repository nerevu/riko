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
from riko.modules import list_modules, regex, tokenizer
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
_MISSING_NAME = "nope"
_DOC = "\nShouts each item.\n\nIgnored trailing prose.\n"


@pytest.fixture
def fixed_registry():
    registry.reset()
    yield registry
    registry.reset()


marker = lambda source, **_: source
MOD_DEFN = ModuleDefinition(name=_NAME, sync_pipe=marker)


def _patch_entry_points(monkeypatch, *eps):
    ep_func = lambda group: list(eps) if group == "riko.modules" else []
    monkeypatch.setattr("riko.ext.registry.entry_points", ep_func)
    registry.reset()  # invalidate the cache memoized by the fixture's pre-test reset


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
    def test_builtin_resolves_lazily(self, fixed_registry):
        assert fixed_registry.resolve("tokenizer", "pipe").__name__ == "pipe"

    def test_missing_module_raises_unsupported(self, fixed_registry):
        with pytest.raises(UnsupportedModuleError):
            fixed_registry.resolve(_MISSING_NAME, "pipe")

    def test_missing_dotted_module_raises_unsupported(self, fixed_registry):
        """
        A dotted name fails to import at its missing parent package, not the full
        target. The guard must still map that to UnsupportedModuleError.
        """
        with pytest.raises(UnsupportedModuleError):
            fixed_registry.resolve("acme.nope", "pipe")

    def test_transitive_import_error_preserved(self, fixed_registry, monkeypatch):
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
            fixed_registry.resolve("tokenizer", "pipe")

        assert not isinstance(e.value, UnsupportedModuleError)

    def test_runtime_registration_takes_precedence(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name="tokenizer", sync_pipe=marker))
        assert fixed_registry.resolve("tokenizer", "pipe") is marker

    def test_register_rejects_duplicate_without_replace(self, fixed_registry):
        fixed_registry.register(MOD_DEFN)

        with pytest.raises(ValueError, match="already registered"):
            fixed_registry.register(MOD_DEFN)

        fixed_registry.register(MOD_DEFN, replace=True)

    def test_registered_module_missing_interface_raises(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name=_MISSING_NAME, sync_pipe=marker))

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.resolve(_MISSING_NAME, "async_pipe")

    def test_runtime_register_requires_name(self, fixed_registry):
        with pytest.raises(ValueError, match="needs a name"):
            fixed_registry.register(ModuleDefinition(sync_pipe=marker))

    def test_module_convention_derives_both_interfaces(self, fixed_registry):
        mod = SimpleNamespace(pipe=marker, async_pipe=marker)
        fixed_registry.register(ModuleDefinition(name=_NAME, module=mod))

        assert fixed_registry.resolve(_NAME, "pipe") is marker
        assert fixed_registry.resolve(_NAME, "async_pipe") is marker

    def test_explicit_callable_overrides_module(self, fixed_registry):
        other = lambda source, **_: source
        mod = SimpleNamespace(pipe=other, async_pipe=other)
        definition = ModuleDefinition(name=_NAME, sync_pipe=marker, module=mod)
        fixed_registry.register(definition)

        assert fixed_registry.resolve(_NAME, "pipe") is marker  # explicit wins
        assert fixed_registry.resolve(_NAME, "async_pipe") is other  # from module


class TestPublicRegister:
    """The public ``riko.ext.register`` surface that targets the global registry."""

    def test_register_resolves_via_facade(self, fixed_registry):
        register(MOD_DEFN)
        assert pipe_resolver.resolve(_NAME, "pipe") is marker
        assert registry.resolve(_NAME, "pipe") is marker

    def test_register_runs_end_to_end(self, fixed_registry):
        """A registered alias of a built-in resolves and runs through SyncPipe"""
        register(ModuleDefinition(name=_NAME, module=tokenizer))
        flow = SyncPipe(_NAME, source=[{"content": "a b c"}], conf={"delimiter": " "})
        assert [item.get("content") for item in flow] == ["a", "b", "c"]

    def test_register_requires_name(self, fixed_registry):
        with pytest.raises(ValueError, match="needs a name"):
            register(ModuleDefinition(sync_pipe=marker))

    def test_reset_registry_clears_registration(self, fixed_registry):
        register(MOD_DEFN)
        reset_registry()

        with pytest.raises(UnsupportedModuleError):
            pipe_resolver.resolve(_NAME, "pipe")


class TestPipeResolver:
    def test_module_resolves_via_registry(self, fixed_registry):
        assert pipe_resolver.resolve("tokenizer", "pipe").__name__ == "pipe"

    def test_pipeline_delegates_to_compiler(self, fixed_registry):
        with pytest.raises(UnsupportedModuleError):
            pipe_resolver.resolve(_MISSING_NAME, "pipe")

    def test_runtime_pipe_resolution_imports_no_compiler(self, fixed_registry):
        """Resolving an ordinary module must not pull in riko.compile."""
        sys.modules.pop("riko.compile", None)
        PipeResolver(fixed_registry, pipeline_resolver).resolve("tokenizer", "pipe")
        assert "riko.compile" not in sys.modules


class TestEntryPointModules:
    """an external package supplies modules via entry points"""

    def test_entry_point_module_resolves(self, monkeypatch, fixed_registry):

        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, MOD_DEFN))
        assert fixed_registry.resolve(_NAME, "pipe") is marker

    def test_name_stamped_from_entry_point_key(self, monkeypatch, fixed_registry):
        """Definition omits name so the registry adopts the entry-point key"""
        defn = ModuleDefinition(sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        assert fixed_registry.resolve(_NAME, "pipe") is marker
        assert fixed_registry._entry_point_definition(_NAME).name == _NAME

    def test_name_key_mismatch_raises(self, monkeypatch, fixed_registry):
        defn = ModuleDefinition(name="acme.other", sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        with pytest.raises(ValueError, match="must match"):
            fixed_registry.resolve(_NAME, "pipe")

    def test_entry_point_via_facade(self, monkeypatch, fixed_registry):
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, MOD_DEFN))
        assert pipe_resolver.resolve(_NAME, "pipe") is marker

    def test_entry_point_may_name_a_bare_module(self, monkeypatch, fixed_registry):
        """The entry point resolves to a module, not a ModuleDefinition"""
        mod = SimpleNamespace(pipe=marker, async_pipe=marker, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        assert fixed_registry.resolve(_NAME, "pipe") is marker
        assert fixed_registry.resolve(_NAME, "async_pipe") is marker

    def test_bare_module_description_from_docstring_summary(
        self, monkeypatch, fixed_registry
    ):
        mod = SimpleNamespace(pipe=marker, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        definition = fixed_registry.definition(_NAME)
        assert definition.name == _NAME
        assert definition.description == "Shouts each item."

    def test_entry_point_without_interfaces_raises(self, monkeypatch, fixed_registry):
        mod = SimpleNamespace(nope=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        with pytest.raises(TypeError, match="expected a ModuleDefinition"):
            fixed_registry.resolve(_NAME, "pipe")

    def test_runtime_registration_shadows_entry_point(
        self, monkeypatch, fixed_registry
    ):
        ep_marker = lambda source, **_: source
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=ep_marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))
        fixed_registry.register(MOD_DEFN)
        resolved = fixed_registry.resolve(_NAME, "pipe")
        assert resolved is marker
        assert resolved is not ep_marker

    def test_entry_points_discovered_lazily_once(self, monkeypatch, fixed_registry):
        calls = {"n": 0}

        def counting(group):
            calls["n"] += 1
            return []

        monkeypatch.setattr("riko.ext.registry.entry_points", counting)
        fixed_registry.reset()

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.resolve(_MISSING_NAME, "pipe")

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.resolve(_MISSING_NAME, "pipe")

        assert calls["n"] == 1


class TestPipelineResolver:
    def test_core_default_has_no_named_pipelines(self):
        """A bare (unconfigured) resolver finds no pipe_* module and no definition"""
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
            MappingStore({"pipe_x": tokenizer}),
            MappingStore({"pipe_x": regex}),
            PackageStore("tests.pypipelines"),
        )
        assert store.load("pipe_x") is tokenizer
        assert store.load("pipe_x") is not regex
        assert store.load("absent") is None

    def test_mapping_store_serves_in_memory_module(self):
        resolver = PipelineResolver(store=MappingStore({"pipe_mem": tokenizer}))
        assert resolver.load("pipe_mem") is tokenizer


class TestCatalog:
    def test_registered_module_appears_in_catalog(self, fixed_registry):
        pipe = _pipe_wrapper(name=_NAME, **_META)
        fixed_registry.register(ModuleDefinition(name=_NAME, sync_pipe=pipe))

        assert _NAME in list_modules()
        assert "tokenizer" in list_modules()  # built-ins still present

    def test_bare_callable_skipped_in_catalog(self, fixed_registry):
        """Resolvable but carries no metadata"""
        fixed_registry.register(MOD_DEFN)

        assert _NAME not in list_modules()
