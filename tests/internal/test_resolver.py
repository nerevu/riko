# vim: sw=4:ts=4:expandtab
"""Tests for the module registry and the pipe-resolution façade."""

from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from riko import Pipeline
from riko.base._paths import ROOT_DIR
from riko.base.exceptions import (
    InvalidPipelineError,
    UnsupportedModuleError,
    UnsupportedWorkflowError,
)
from riko.definitions._workflow import Workflow
from riko.definitions.modules import ModuleDefinition
from riko.ext import register_module
from riko.ext.codegen import list_modules
from riko.ext.registry import reset_module_registry
from riko.modules import regex, tokenizer
from riko.runtime._importutils import require_interface
from riko.runtime._module_registry import module_registry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflows import (
    CompositeStore,
    DirectoryStore,
    MappingStore,
    PackageStore,
    WorkflowResolver,
)
from riko.types._guards import is_mapping
from tests import pyworkflows

if TYPE_CHECKING:
    from riko.types._wrappers import SyncModuleWrapper

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
    module_registry.reset()
    yield module_registry
    module_registry.reset()


marker = cast("SyncModuleWrapper", lambda source, **_: source)
MOD_DEFN = ModuleDefinition(name=_NAME, sync_pipe=marker)


def _patch_entry_points(monkeypatch, *eps):
    ep_func = lambda group: list(eps) if group == "riko.modules" else []
    monkeypatch.setattr("riko.runtime._registry.entry_points", ep_func)
    # invalidate the cache memoized by the fixture's pre-test reset
    module_registry.reset()


def _pipe_wrapper(**attrs):
    wrapper = cast("SyncModuleWrapper", lambda source, **_: source)

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
        assert fixed_registry.require("tokenizer").__name__ == "pipe"

    def test_missing_module_raises_unsupported(self, fixed_registry):
        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME)

    def test_missing_dotted_module_raises_unsupported(self, fixed_registry):
        """
        Map missing parents in dotted names to ``UnsupportedModuleError``.

        The import fails at the missing parent rather than the full target.
        """
        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require("acme.nope")

    def test_transitive_import_error_preserved(self, fixed_registry, monkeypatch):
        """Preserve ``ModuleNotFoundError`` for missing internal dependencies."""

        def fake_import(name, *args, **kwargs):
            if name == "riko.modules.tokenizer":
                raise ModuleNotFoundError("No module named 'ghost'", name="ghost")

            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("riko.base._imports.import_module", fake_import)

        with pytest.raises(ModuleNotFoundError) as e:
            fixed_registry.require("tokenizer")

        assert not isinstance(e.value, UnsupportedModuleError)

    def test_runtime_registration_takes_precedence(self, fixed_registry):
        definition = ModuleDefinition(name="tokenizer", sync_pipe=marker)
        fixed_registry.register(definition, replace=True)
        assert fixed_registry.require("tokenizer") is marker

    def test_register_rejects_builtin_shadow_without_replace(self, fixed_registry):
        with pytest.raises(ValueError, match="shadows a built-in module"):
            fixed_registry.register(ModuleDefinition(name="count", sync_pipe=marker))

        assert fixed_registry.registered_names() == ()

    def test_registered_names_are_sorted(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name="zeta", sync_pipe=marker))
        fixed_registry.register(ModuleDefinition(name="alpha", sync_pipe=marker))
        assert fixed_registry.registered_names() == ("alpha", "zeta")

    def test_register_rejects_duplicate_without_replace(self, fixed_registry):
        fixed_registry.register(MOD_DEFN)

        with pytest.raises(ValueError, match="already registered"):
            fixed_registry.register(MOD_DEFN)

        fixed_registry.register(MOD_DEFN, replace=True)

    def test_registered_module_missing_interface_raises(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name=_MISSING_NAME, sync_pipe=marker))

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME, True)

    def test_runtime_register_requires_name(self, fixed_registry):
        with pytest.raises(ValueError, match="needs a name"):
            fixed_registry.register(ModuleDefinition(sync_pipe=marker))

    def test_module_convention_derives_both_interfaces(self, fixed_registry):
        mod = SimpleNamespace(pipe=marker, async_pipe=marker)
        fixed_registry.register(ModuleDefinition(name=_NAME, module=mod))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry.require(_NAME, True) is marker

    def test_explicit_callable_overrides_module(self, fixed_registry):
        other = cast("SyncModuleWrapper", lambda source, **_: source)
        mod = SimpleNamespace(pipe=other, async_pipe=other)
        definition = ModuleDefinition(name=_NAME, sync_pipe=marker, module=mod)
        fixed_registry.register(definition)

        assert fixed_registry.require(_NAME) is marker  # explicit wins
        assert fixed_registry.require(_NAME, True) is other  # from module


class TestPublicRegister:
    """Public ``riko.ext.module_registry`` surface that targets the global registry."""

    def test_register_resolves_via_facade(self, fixed_registry):
        register_module(MOD_DEFN)
        assert dispatcher.require(_NAME) is marker
        assert module_registry.require(_NAME) is marker

    def test_register_runs_end_to_end(self, fixed_registry):
        """A registered alias of a built-in resolves and runs through a pipeline."""
        register_module(ModuleDefinition(name=_NAME, module=tokenizer))
        source = Pipeline(source=[{"content": "a b c"}])
        pipeline = source.pipe(_NAME, conf={"delimiter": " "})
        expected = ["a", "b", "c"]
        assert [
            item.get("content") for item in pipeline if is_mapping(item)
        ] == expected

    def test_reset_registry_clears_registration(self, fixed_registry):
        register_module(MOD_DEFN)
        reset_module_registry()

        with pytest.raises(UnsupportedModuleError):
            dispatcher.require(_NAME)


class TestResolverDispatcher:
    def test_module_resolves_via_registry(self, fixed_registry):
        assert dispatcher.require("tokenizer").__name__ == "pipe"

    def test_non_stored_workflow_name_routes_to_module_registry(self, fixed_registry):
        # A plain (non ``pipe_*``) name resolves through the module registry, so a
        # miss surfaces as UnsupportedModuleError, not UnsupportedWorkflowError.
        with pytest.raises(UnsupportedModuleError):
            dispatcher.require(_MISSING_NAME)

    def test_missing_stored_workflow_raises(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies") as err:
            dispatcher.require("pipe_missing")

        assert err.value.pipe_id == "pipe_missing"

    def test_missing_stored_workflow_interfaces_raise(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies"):
            WorkflowResolver().require_interfaces("pipe_missing")

    def test_stored_workflow_without_interfaces_fails_validation_as_a_workflow(self):
        store = MappingStore({"pipe_empty": ModuleType("pipe_empty")})
        resolver = WorkflowResolver(module_store=store)
        local = ResolverDispatcher(module_registry, resolver)

        with pytest.raises(UnsupportedWorkflowError, match="no interfaces"):
            local.validate("pipe_empty")

    @pytest.mark.xfail(
        strict=True,
        reason="a runtime-registered pipe_* module is routed to the workflow "
        "resolver by name prefix and raises UnsupportedWorkflowError.",
    )
    def test_runtime_registered_pipe_prefixed_module_resolves(self, fixed_registry):
        """
        Prefer runtime registrations whose names start with ``pipe_``.

        These registrations must resolve to the registered callable rather than
        stored-workflow (``pipe_<id>``) name routing.
        """
        name = "pipe_transform"
        fixed_registry.register(ModuleDefinition(name=name, sync_pipe=marker))
        assert dispatcher.require(name) is marker


class TestRequireInterface:
    """A missing interface names the right kind of thing and keeps the bare name."""

    def test_builtin_module_without_interface_is_a_module_error(self):
        def loader(name):
            return ModuleType(name)

        with pytest.raises(UnsupportedModuleError, match="has no 'async_pipe'") as err:
            require_interface("bare", is_async=True, loader=loader)

        assert err.value.module_name == "bare"

    def test_stored_workflow_without_interface_is_a_workflow_error(self):
        def loader(name):
            return ModuleType(name)

        with pytest.raises(UnsupportedWorkflowError, match="has no 'pipe'") as err:
            require_interface("pipe_bare", builtin=False, loader=loader)

        assert err.value.pipe_id == "pipe_bare"


class TestEntryPointModules:
    """an external package supplies modules via entry points."""

    def test_entry_point_module_resolves(self, monkeypatch, fixed_registry):

        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, MOD_DEFN))
        assert fixed_registry.require(_NAME) is marker

    def test_name_stamped_from_entry_point_key(self, monkeypatch, fixed_registry):
        """Definition omits name so the registry adopts the entry-point key."""
        defn = ModuleDefinition(sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry._entry_point(_NAME).name == _NAME

    def test_name_key_mismatch_raises(self, monkeypatch, fixed_registry):
        defn = ModuleDefinition(name="acme.other", sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        with pytest.raises(ValueError, match="must match"):
            fixed_registry.require(_NAME)

    def test_entry_point_via_facade(self, monkeypatch, fixed_registry):
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, MOD_DEFN))
        assert dispatcher.require(_NAME) is marker

    def test_entry_point_may_name_a_bare_module(self, monkeypatch, fixed_registry):
        """The entry point resolves to a module, not a ModuleDefinition."""
        mod = SimpleNamespace(pipe=marker, async_pipe=marker, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry.require(_NAME, True) is marker

    def test_bare_module_description_from_docstring_summary(
        self, monkeypatch, fixed_registry
    ):
        mod = SimpleNamespace(pipe=marker, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        definition = fixed_registry.load_definition(_NAME)
        assert definition.name == _NAME
        assert definition.description == "Shouts each item."

    def test_entry_point_without_interfaces_raises(self, monkeypatch, fixed_registry):
        mod = SimpleNamespace(nope=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        with pytest.raises(TypeError, match="expected a ModuleDefinition"):
            fixed_registry.require(_NAME)

    def test_runtime_registration_shadows_entry_point(
        self, monkeypatch, fixed_registry
    ):
        ep_marker = cast("SyncModuleWrapper", lambda source, **_: source)
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=ep_marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))
        fixed_registry.register(MOD_DEFN, replace=True)
        resolved = fixed_registry.require(_NAME)
        assert resolved is marker
        assert resolved is not ep_marker

    def test_register_rejects_entry_point_shadow_without_replace(
        self, monkeypatch, fixed_registry
    ):
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))

        with pytest.raises(ValueError, match="shadows an entry-point module"):
            fixed_registry.register(MOD_DEFN)

    def test_entry_points_discovered_lazily_once(self, monkeypatch, fixed_registry):
        calls = {"n": 0}

        def counting(group):
            calls["n"] += 1
            return []

        monkeypatch.setattr("riko.runtime._registry.entry_points", counting)
        fixed_registry.reset()

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME)

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME)

        assert calls["n"] == 1


class TestWorkflowResolver:
    def test_core_default_has_no_stored_workflows(self):
        """A bare (unconfigured) resolver finds no pipe_* module and no workflow."""
        resolver = WorkflowResolver()
        assert resolver.load("pipe_x") is None

        with pytest.raises(UnsupportedWorkflowError, match="no document store"):
            resolver.load_workflow("pipe_x")

    def test_configured_resolver_loads_resolved_workflow(self):
        resolver = WorkflowResolver(module_store=PackageStore("tests.pyworkflows"))
        assert resolver.load("pipe_kazeeki1") is not None

    def test_missing_module_returns_none(self):
        resolver = WorkflowResolver(module_store=PackageStore("tests.pyworkflows"))
        assert resolver.load("pipe_missing") is None

    def test_interfaces_accept_the_colon_alias(self):
        module = ModuleType("pipe_demo")
        setattr(module, "pipe", tokenizer.pipe)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
        assert resolver.require_interfaces("pipe:demo") == {"pipe"}

    def test_async_interface_is_tagged_async_whatever_its_name(self):
        """An async interface not named ``async_pipe`` is still tagged async."""

        async def gen_items(item=None, **kwargs):
            yield {"x": 1}

        module = ModuleType("pipe_demo")
        setattr(module, "pipe", lambda item=None, **kwargs: iter([]))  # noqa: B010
        setattr(module, "async_pipe", gen_items)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
        assert resolver.require("pipe:demo", is_async=True).isasync
        assert not resolver.require("pipe:demo").isasync

    def test_second_document_store_requires_replace(self, tmp_path):
        resolver = WorkflowResolver(document_store=DirectoryStore(tmp_path))

        with pytest.raises(ValueError, match="document store already registered"):
            resolver.register(document_store=DirectoryStore(tmp_path))

    def test_load_accepts_the_colon_alias(self):
        """``pipe:<id>`` finds the same stored workflow ``require`` does."""
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_mem": tokenizer}))
        assert resolver.load("pipe:mem") is resolver.load("pipe_mem")
        assert resolver.load("pipe:mem") is not None

    def test_load_workflow_accepts_the_colon_alias(self):
        directory = ROOT_DIR / "tests" / "workflows"
        resolver = WorkflowResolver(document_store=DirectoryStore(directory))
        assert resolver.load_workflow("pipe:gigs") == resolver.load_workflow(
            "pipe_gigs"
        )

    def test_package_store_accepts_the_package_itself(self):
        resolver = WorkflowResolver(module_store=PackageStore(pyworkflows))
        assert resolver.load("pipe_kazeeki1") is not None

    def test_mistyped_package_path_raises_when_built(self):
        with pytest.raises(ModuleNotFoundError, match="no_such_package"):
            PackageStore("tests.no_such_package")

    def test_a_plain_module_is_not_a_package(self):
        with pytest.raises(ValueError, match="is a module, not a package"):
            PackageStore(tokenizer)

    def test_directory_store_parses_workflow(self):
        directory = ROOT_DIR / "tests" / "workflows"
        resolver = WorkflowResolver(document_store=DirectoryStore(directory))
        assert isinstance(resolver.load_workflow("pipe_gigs"), Workflow)

        with pytest.raises(
            UnsupportedWorkflowError, match="no WorkflowDocument"
        ) as err:
            resolver.load_workflow("pipe_missing")

        assert err.value.pipe_id == "pipe_missing"

    def test_directory_store_surfaces_unreadable_documents(self, tmp_path):
        """Only a missing document is a miss; an unreadable one is an error."""
        (tmp_path / "pipe_dir.json").mkdir()
        store = DirectoryStore(tmp_path)
        assert store.load("pipe_absent") is None

        with pytest.raises(OSError, match=r"pipe_dir\.json"):
            store.load("pipe_dir")

    def test_composite_store_first_hit_wins(self):
        store = CompositeStore(
            MappingStore({"pipe_x": tokenizer}),
            MappingStore({"pipe_x": regex}),
            PackageStore("tests.pyworkflows"),
        )
        assert store.load("pipe_x") is tokenizer
        assert store.load("pipe_x") is not regex
        assert store.load("absent") is None

    def test_mapping_store_returns_the_supplied_module(self):
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_mem": tokenizer}))
        assert resolver.load("pipe_mem") is tokenizer


class TestCatalog:
    def test_registered_module_appears_in_catalog(self, fixed_registry):
        pipe = _pipe_wrapper(name=_NAME, **_META)
        fixed_registry.register(ModuleDefinition(name=_NAME, sync_pipe=pipe))

        assert _NAME in list_modules()
        assert "tokenizer" in list_modules()  # built-ins still present

    def test_bare_callable_skipped_in_catalog(self, fixed_registry):
        """Resolvable but carries no metadata."""
        fixed_registry.register(MOD_DEFN)

        assert _NAME not in list_modules()


def _document_resolver(directory, **kwargs) -> WorkflowResolver:
    """Builds a resolver whose document modules run through the global dispatcher."""
    resolver = WorkflowResolver(document_store=DirectoryStore(directory), **kwargs)
    resolver.register_dispatcher(dispatcher)
    return resolver


class TestResolvedDocuments:
    workflows = ROOT_DIR / "tests" / "workflows"

    def test_document_loads_once_with_both_interfaces(self):
        resolver = _document_resolver(self.workflows)
        module = resolver.load("pipe_gigs")

        assert module is not None
        assert callable(module.pipe)
        assert callable(module.async_pipe)
        assert resolver.load("pipe_gigs") is module
        assert resolver.require_interfaces("pipe_gigs") == {"pipe", "async_pipe"}

    def test_reset_forgets_resolved_documents(self):
        resolver = _document_resolver(self.workflows)
        assert resolver.load("pipe_gigs") is not None

        resolver.reset()
        assert resolver.load("pipe_gigs") is None

    def test_replacing_documents_reloads_them(self, tmp_path):
        source = self.workflows / "pipe_gigs.json"
        (tmp_path / "pipe_gigs.json").write_bytes(source.read_bytes())
        resolver = _document_resolver(self.workflows)
        first = resolver.load("pipe_gigs")

        resolver.register(document_store=DirectoryStore(tmp_path), replace=True)
        second = resolver.load("pipe_gigs")

        assert second is not None
        assert second is not first

    def test_module_store_wins_over_document(self):
        store = MappingStore({"pipe_gigs": tokenizer})
        resolver = _document_resolver(self.workflows, module_store=store)
        assert resolver.load("pipe_gigs") is tokenizer

    def test_malformed_document_raises_invalid_pipeline(self, tmp_path):
        (tmp_path / "pipe_bad.json").write_text("{bad")
        resolver = _document_resolver(tmp_path)

        with pytest.raises(InvalidPipelineError, match="malformed"):
            resolver.require("pipe_bad")

    def test_document_without_dispatcher_raises(self):
        resolver = WorkflowResolver(document_store=DirectoryStore(self.workflows))

        with pytest.raises(UnsupportedWorkflowError, match="no dispatcher"):
            resolver.load("pipe_gigs")

    def test_registering_a_dispatcher_rebuilds_documents(self):
        resolver = _document_resolver(self.workflows)
        first = resolver.load("pipe_gigs")

        resolver.register_dispatcher(dispatcher)
        second = resolver.load("pipe_gigs")

        assert second is not None
        assert second is not first
