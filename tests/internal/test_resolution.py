# vim: sw=4:ts=4:expandtab
"""Provides internal tests for module and workflow resolution."""

from __future__ import annotations

import re
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import attrs
import pytest

from riko.base._exceptions import (
    InvalidPipelineError,
    UnsupportedModuleError,
    UnsupportedWorkflowError,
)
from riko.base._guards import is_mapping
from riko.base._paths import TESTS_DIR
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._workflow_definition import Workflow
from riko.modules import describe_module
from riko.modules import regex as regex_module
from riko.modules import tokenizer as tokenizer_module
from riko.modules._metadata import get_module_metadata, list_modules
from riko.modules.truncate import pipe as truncate
from riko.runtime._importutils import require_interface
from riko.runtime._module_registry import (
    module_registry,
    register_module,
    reset_module_registry,
)
from riko.runtime._pipeline import Pipeline
from riko.runtime._registry import Registry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_pipes import build_workflow_pipes, workflow
from riko.runtime._workflow_resolver import WorkflowResolver, _build_resolved_workflow
from riko.runtime._workflow_stores import (
    CompositeStore,
    DirectoryStore,
    MappingStore,
    PackageStore,
)
from riko.types._enums import ExecutionMode
from tests import pyworkflows
from tests._execution import module_workflow, registered_modules
from tests._workflows import register_documents

if TYPE_CHECKING:
    from riko.types._wrappers import SyncModuleWrapper


def _pipe_wrapper(**attrs):
    wrapper = cast("SyncModuleWrapper", lambda source, **_: source)

    for key, value in attrs.items():
        setattr(wrapper, key, value)

    return wrapper


_NAME = "acme.mod"
_MISSING_NAME = "nope"
_MARKER = _pipe_wrapper()
_DOC = "\nShouts each item.\n\nIgnored trailing prose.\n"

_META = {
    "type": "operator",
    "subtype": "composer",
    "subtypes": {"composer"},
    "pollable": False,
    "loopable": False,
    "isasync": False,
}

MOD_DEFN = ModuleDefinition(name=_NAME, sync_pipe=_MARKER)


@pytest.fixture
def fixed_registry():
    with registered_modules() as registry:
        yield registry


class TestWorkflowDecorator:
    def test_returns_a_tagged_copy(self):
        tagged = workflow(subtype="transformer")(truncate)

        assert tagged is not truncate
        assert truncate.type == "operator"
        assert truncate.name == "truncate"
        assert tagged.type == "pipe"
        assert get_module_metadata("truncate", strict=True).type == "operator"

    def test_rejects_positional_arguments(self):
        with pytest.raises(TypeError, match="Pipeline"):
            workflow(object())  # pyright: ignore[reportCallIssue]


class TestBuildWorkflowPipes:
    def test_an_unseeded_pipe_requires_a_seed(self):
        flow = module_workflow("reverse")
        pipes = build_workflow_pipes(flow, dispatcher, subtype="transformer")

        with pytest.raises(InvalidPipelineError, match="requires a seed"):
            list(pipes.sync_pipe())


class _FalsyPipe:
    """A pipe callable whose truthiness is ``False`` but which still has a name."""

    __name__ = "double"

    def __bool__(self) -> bool:
        return False

    def __call__(self, source, **kwargs):
        return source


class TestModuleRegistry:
    @pytest.mark.parametrize(
        ("method", "arg"),
        [
            pytest.param("_key", "entry", id="key"),
            pytest.param("_load", SimpleNamespace(name="entry"), id="load"),
        ],
    )
    def test_base_registry_requires_subclass_hooks(self, method, arg):
        with pytest.raises(NotImplementedError, match=rf"Registry\.{method} must"):
            getattr(Registry(), method)(arg)

    def test_builtin_resolves_lazily(self, fixed_registry):
        assert fixed_registry.require("tokenizer").__name__ == "pipe"

    @pytest.mark.parametrize("method", ["require", "require_interfaces"])
    def test_missing_module_hints_at_close_matches(self, fixed_registry, method):
        with pytest.raises(
            UnsupportedModuleError, match=r"did you mean 'truncate'\?"
        ) as e:
            getattr(fixed_registry, method)("trunkate")

        assert e.value.module_name == "trunkate"
        assert e.value.matches == ("truncate",)

    def test_missing_module_without_close_match_keeps_the_bare_message(
        self, fixed_registry
    ):
        with pytest.raises(UnsupportedModuleError) as e:
            fixed_registry.require(_MISSING_NAME)

        assert str(e.value) == f"Unsupported riko module: {_MISSING_NAME}"

    def test_missing_dotted_module_raises_unsupported(self, fixed_registry):
        """
        Rejects a dotted name as an unknown module.

        A dotted name is not a built-in, so the registry refuses it before any
        import is attempted.
        """
        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require("acme.nope")

    def test_transitive_import_error_preserved(self, fixed_registry, monkeypatch):
        """Preserve ``ModuleNotFoundError`` for missing internal dependencies."""

        def fake_import(name, *args, **kwargs):
            if name == "riko.modules.tokenizer":
                raise ModuleNotFoundError("No module named 'ghost'", name="ghost")

            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("riko.base._typing.import_module", fake_import)

        with pytest.raises(ModuleNotFoundError) as e:
            fixed_registry.require("tokenizer")

        assert not isinstance(e.value, UnsupportedModuleError)

    def test_runtime_registration_takes_precedence(self, fixed_registry):
        definition = ModuleDefinition(name="tokenizer", sync_pipe=_MARKER)
        fixed_registry.register(definition, replace=True)
        assert fixed_registry.require("tokenizer") is _MARKER

    def test_register_rejects_builtin_shadow_without_replace(self, fixed_registry):
        with pytest.raises(ValueError, match="shadows a built-in module"):
            fixed_registry.register(ModuleDefinition(name="count", sync_pipe=_MARKER))

        assert fixed_registry.registered_names == ()

    def test_registered_names_are_sorted(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name="zeta", sync_pipe=_MARKER))
        fixed_registry.register(ModuleDefinition(name="alpha", sync_pipe=_MARKER))
        assert fixed_registry.registered_names == ("alpha", "zeta")

    def test_register_rejects_duplicate_without_replace(self, fixed_registry):
        fixed_registry.register(MOD_DEFN)

        with pytest.raises(ValueError, match="already registered"):
            fixed_registry.register(MOD_DEFN)

        fixed_registry.register(MOD_DEFN, replace=True)

    def test_registered_module_missing_interface_raises(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name=_MISSING_NAME, sync_pipe=_MARKER))

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME, True)

    def test_runtime_register_requires_name(self, fixed_registry):
        with pytest.raises(ValueError, match="needs a name"):
            fixed_registry.register(ModuleDefinition(sync_pipe=_MARKER))

    def test_falsy_callable_supplies_name(self):
        pipe = cast("SyncModuleWrapper", _FalsyPipe())
        assert ModuleDefinition(sync_pipe=pipe).name == "double"

    def test_module_convention_snapshots_at_construction(self, fixed_registry):
        other = _pipe_wrapper()
        mod = SimpleNamespace(pipe=_MARKER, __name__="pkg.snap")
        definition = ModuleDefinition.from_module(mod)
        fixed_registry.register(definition)
        mod.pipe = other
        mod.__name__ = "pkg.other"

        assert definition.name == "snap"
        assert attrs.evolve(definition, description="z").name == "snap"
        assert fixed_registry.require("snap") is _MARKER

    def test_module_convention_derives_both_interfaces(self, fixed_registry):
        mod = SimpleNamespace(pipe=_MARKER, async_pipe=_MARKER)
        fixed_registry.register(ModuleDefinition.from_module(mod, name=_NAME))

        assert fixed_registry.require(_NAME) is _MARKER
        assert fixed_registry.require(_NAME, True) is _MARKER

    def test_module_convention_description_override(self):
        mod = SimpleNamespace(pipe=_MARKER, __doc__="Shouts.")
        definition = ModuleDefinition.from_module(mod, description="Yells.")
        assert definition.description == "Yells."

    def test_explicit_callable_overrides_module(self, fixed_registry):
        other = _pipe_wrapper()
        mod = SimpleNamespace(pipe=other, async_pipe=other)
        derived = ModuleDefinition.from_module(mod, name=_NAME)
        definition = attrs.evolve(derived, sync_pipe=_MARKER)
        fixed_registry.register(definition)

        assert fixed_registry.require(_NAME) is _MARKER  # explicit wins
        assert fixed_registry.require(_NAME, True) is other  # from module


class TestDescribeModule:
    @pytest.mark.parametrize(
        ("error", "match"),
        [
            pytest.param(
                ModuleNotFoundError(
                    "No module named 'phantom_dep'", name="phantom_dep"
                ),
                "phantom_dep",
                id="nested-dependency",
            ),
            pytest.param(
                ModuleNotFoundError("broken import with no module name"),
                "no module name",
                id="unnamed",
            ),
        ],
    )
    def test_describe_module_reraises_import_error(
        self, monkeypatch, error: ModuleNotFoundError, match: str
    ):
        def boom(target):
            raise error

        monkeypatch.setattr("riko.base._typing.import_module", boom)

        with pytest.raises(ModuleNotFoundError, match=match):
            describe_module("hash")


class TestPublicRegister:
    """Exercise ``register_module`` against the process-global registry."""

    def test_register_resolves_via_global_registry(self, fixed_registry):
        register_module(MOD_DEFN)
        assert dispatcher.require(_NAME) is _MARKER
        assert module_registry.require(_NAME) is _MARKER

    def test_register_runs_end_to_end(self, fixed_registry):
        """A registered alias of a built-in resolves and runs through a pipeline."""
        register_module(ModuleDefinition.from_module(tokenizer_module, name=_NAME))
        pipeline = Pipeline.from_module(_NAME, conf={"delimiter": " "})
        stream = pipeline([{"content": "a b c"}])
        expected = ["a", "b", "c"]
        assert [item.get("content") for item in stream if is_mapping(item)] == expected

    def test_reset_registry_clears_registration(self, fixed_registry):
        register_module(MOD_DEFN)
        reset_module_registry()

        with pytest.raises(UnsupportedModuleError):
            dispatcher.require(_NAME)


class TestResolverDispatcher:
    def test_non_stored_workflow_name_routes_to_module_registry(self, fixed_registry):
        # A plain (non ``pipe_*``) name resolves through the module registry, so a
        # miss surfaces as UnsupportedModuleError, not UnsupportedWorkflowError.
        with pytest.raises(UnsupportedModuleError):
            dispatcher.require(_MISSING_NAME)

    def test_missing_stored_workflow_raises(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies") as err:
            dispatcher.require("pipe_missing")

        assert err.value.pipe_id == "pipe_missing"

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
        fixed_registry.register(ModuleDefinition(name=name, sync_pipe=_MARKER))
        assert dispatcher.require(name) is _MARKER


class TestRequireInterface:
    """A missing interface names the right kind of thing and keeps the bare name."""

    def test_missing_builtin_module_is_a_module_error(self):
        with pytest.raises(UnsupportedModuleError) as err:
            require_interface("nope")

        assert err.value.module_name == "nope"

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


def _patch_entry_points(monkeypatch, *eps):
    ep_func = lambda group: list(eps) if group == "riko.modules" else []
    monkeypatch.setattr("riko.runtime._registry.entry_points", ep_func)
    # invalidate the cache memoized by the fixture's pre-test reset
    module_registry.reset()


class _FakeEntryPoint:
    """Mimics ``EntryPoint``: equal when name and value agree, whatever the dist."""

    def __init__(self, name, definition, dist=None):
        self.name = name
        self.value = f"fake:{id(definition)}"
        self.dist = None if dist is None else SimpleNamespace(name=dist)
        self._definition = definition

    def __eq__(self, other):
        return (self.name, self.value) == (other.name, other.value)

    def __hash__(self):
        return hash((self.name, self.value))

    def load(self):
        return self._definition


class TestEntryPointModules:
    """an external package supplies modules via entry points."""

    def test_entry_point_module_resolves(self, monkeypatch, fixed_registry):

        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, MOD_DEFN))
        assert fixed_registry.require(_NAME) is _MARKER

    def test_name_stamped_from_entry_point_key(self, monkeypatch, fixed_registry):
        """Definition omits name so the registry adopts the entry-point key."""
        defn = ModuleDefinition(sync_pipe=_MARKER)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        assert fixed_registry.require(_NAME) is _MARKER
        assert fixed_registry._load_entry_point(_NAME).name == _NAME

    def test_name_key_mismatch_raises(self, monkeypatch, fixed_registry):
        defn = ModuleDefinition(name="acme.other", sync_pipe=_MARKER)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        with pytest.raises(ValueError, match="must match"):
            fixed_registry.require(_NAME)

    def test_from_module_definition_must_name_the_entry_point(
        self, monkeypatch, fixed_registry
    ):
        """A module-derived name declares the module tail, so the key must match it."""
        mod = SimpleNamespace(pipe=_MARKER, __name__="pkg.shout")
        defn = ModuleDefinition.from_module(mod)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        with pytest.raises(ValueError, match="must match"):
            fixed_registry.require(_NAME)

        named = ModuleDefinition.from_module(mod, name=_NAME)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, named))
        assert fixed_registry.require(_NAME) is _MARKER

    def test_entry_point_may_name_a_bare_module(self, monkeypatch, fixed_registry):
        """The entry point resolves to a module, not a ModuleDefinition."""
        mod = SimpleNamespace(pipe=_MARKER, async_pipe=_MARKER, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        assert fixed_registry.require(_NAME) is _MARKER
        assert fixed_registry.require(_NAME, True) is _MARKER

    def test_bare_module_description_from_docstring_summary(
        self, monkeypatch, fixed_registry
    ):
        mod = SimpleNamespace(pipe=_MARKER, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        definition = fixed_registry.load_definition(_NAME)
        assert definition.name == _NAME
        assert definition.description == "Shouts each item."

    def test_entry_point_without_interfaces_raises(self, monkeypatch, fixed_registry):
        mod = SimpleNamespace(nope=_MARKER)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        with pytest.raises(TypeError, match="expected a ModuleDefinition"):
            fixed_registry.require(_NAME)

    def test_runtime_registration_shadows_entry_point(
        self, monkeypatch, fixed_registry
    ):
        ep_marker = _pipe_wrapper()
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=ep_marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))
        fixed_registry.register(MOD_DEFN, replace=True)
        resolved = fixed_registry.require(_NAME)
        assert resolved is _MARKER
        assert resolved is not ep_marker

    def test_register_rejects_entry_point_shadow_without_replace(
        self, monkeypatch, fixed_registry
    ):
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=_MARKER)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))

        with pytest.raises(ValueError, match="shadows an entry-point module"):
            fixed_registry.register(MOD_DEFN)

    def test_duplicate_entry_point_names_raise(self, monkeypatch, fixed_registry):
        other = ModuleDefinition(name=_NAME, sync_pipe=_MARKER)
        acme = _FakeEntryPoint(_NAME, MOD_DEFN, dist="acme")
        globex = _FakeEntryPoint(_NAME, other, dist="globex")
        _patch_entry_points(monkeypatch, acme, globex)

        with pytest.raises(ValueError, match="acme, globex"):
            fixed_registry.require(_NAME)

    def test_an_entry_point_listed_twice_resolves(self, monkeypatch, fixed_registry):
        twice = _FakeEntryPoint(_NAME, MOD_DEFN, dist="acme")
        _patch_entry_points(monkeypatch, twice, twice)

        assert fixed_registry.require(_NAME) is _MARKER

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


EMBED_CYCLES = [
    pytest.param({"pipe_a": ["pipe_a"]}, "pipe_a -> pipe_a", id="direct"),
    pytest.param(
        {"pipe_a": ["pipe_b"], "pipe_b": ["pipe_a"]},
        "pipe_a -> pipe_b -> pipe_a",
        id="via",
    ),
    pytest.param({"pipe_a": [{"loop": "pipe_a"}]}, "pipe_a -> pipe_a", id="loop-embed"),
    pytest.param(
        {"pipe_a": ["pipe_b"], "pipe_b": ["pipe_c"], "pipe_c": ["pipe_b"]},
        "pipe_b -> pipe_c -> pipe_b",
        id="tail",
    ),
    pytest.param(
        {"pipe_a": ["pipe_b"], "pipe_b": ["pipe_c"], "pipe_c": ["forever"]},
        None,
        id="chain",
    ),
]


def _stored_resolver(
    documents: dict[str, list[str | dict[str, str]]],
) -> WorkflowResolver:
    """Builds a resolver over stored workflows that name ``documents``' values."""

    def node(dependency: str | dict[str, str]) -> dict[str, object]:
        if isinstance(dependency, dict):
            result: dict[str, object] = {
                "name": "loop",
                "embed": {"name": dependency["loop"]},
            }
        else:
            result = {"name": dependency}

        return result

    modules = {
        name: _build_resolved_workflow(
            name, Workflow.parse({"nodes": [node(dep) for dep in deps]}), dispatcher
        )
        for name, deps in documents.items()
    }
    return WorkflowResolver(module_store=MappingStore(modules))


def _demo_resolver(**interfaces: object) -> WorkflowResolver:
    module = ModuleType("pipe_demo")

    for name, value in interfaces.items():
        setattr(module, name, value)

    return WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))


class TestWorkflowResolver:
    def test_core_default_has_no_stored_workflows(self):
        """A bare (unconfigured) resolver finds no pipe_* module and no workflow."""
        resolver = WorkflowResolver()
        assert resolver.load("pipe_x") is None

        with pytest.raises(UnsupportedWorkflowError, match="no document store"):
            resolver.load_workflow("pipe_x")

    @pytest.mark.parametrize(
        "package",
        [
            pytest.param("tests.pyworkflows", id="import-path"),
            pytest.param(pyworkflows, id="package"),
        ],
    )
    def test_configured_resolver_loads_resolved_workflow(self, package):
        resolver = WorkflowResolver(module_store=PackageStore(package))
        assert resolver.load("pipe_kazeeki1") is not None

    def test_interfaces_accept_the_colon_alias(self):
        resolver = _demo_resolver(pipe=tokenizer_module.pipe)
        assert resolver.require_interfaces("pipe:demo") == {"pipe"}

    def test_require_tags_a_copy_and_leaves_the_module_pipe_untouched(self):
        def plain(item=None, **kwargs):
            return iter([{"x": 1}])

        module = ModuleType("pipe_demo")
        setattr(module, "pipe", plain)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
        first = resolver.require("pipe_demo")
        second = resolver.require("pipe_demo")

        assert module.pipe is plain
        assert not hasattr(plain, "type")
        assert first is not plain
        assert second is not plain
        assert first.type == second.type == "pipe"

    def test_require_returns_an_already_tagged_pipe_by_identity(self):
        tagged = workflow(subtype="transformer")(lambda item=None, **_: iter([]))
        resolver = _demo_resolver(pipe=tagged)
        assert resolver.require("pipe_demo") is tagged

    def test_async_pipe_callable_is_tagged_async_whatever_its_name(self):
        """An async pipe callable not named ``async_pipe`` is still tagged async."""

        async def gen_items(item=None, **kwargs):
            yield {"x": 1}

        resolver = _demo_resolver(
            pipe=lambda item=None, **kwargs: iter([]), async_pipe=gen_items
        )
        assert resolver.require("pipe:demo", is_async=True).isasync
        assert not resolver.require("pipe:demo").isasync

    def test_load_workflow_accepts_the_colon_alias(self):
        directory = TESTS_DIR / "workflows"
        resolver = WorkflowResolver(document_store=DirectoryStore(directory))
        assert resolver.load_workflow("pipe:gigs") == resolver.load_workflow(
            "pipe_gigs"
        )

    def test_second_document_store_requires_replace(self, tmp_path):
        resolver = WorkflowResolver(document_store=DirectoryStore(tmp_path))

        with pytest.raises(ValueError, match="document store already registered"):
            resolver.register(document_store=DirectoryStore(tmp_path))

    def test_missing_stored_workflow_interfaces_raise(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies"):
            WorkflowResolver().require_interfaces("pipe_missing")

    @pytest.mark.parametrize(("documents", "cycle"), EMBED_CYCLES)
    def test_require_rejects_a_stored_workflow_that_embeds_itself(
        self, documents, cycle
    ) -> None:
        """A stored workflow that reaches itself is refused instead of recursing."""
        resolver = _stored_resolver(documents)

        if cycle is None:
            assert resolver.require("pipe_a").type == "pipe"
        else:
            match = rf"embeds itself \({re.escape(cycle)}\)\. .* from a 'loop' node"

            with pytest.raises(InvalidPipelineError, match=match):
                resolver.require("pipe_a")


class TestPackageStore:
    def test_a_plain_module_is_not_a_package(self):
        with pytest.raises(ValueError, match="is a module, not a package"):
            PackageStore(tokenizer_module)

    def test_mistyped_package_path_raises_when_built(self):
        with pytest.raises(ModuleNotFoundError, match="no_such_package"):
            PackageStore("tests.no_such_package")


class TestDirectoryStore:
    def test_directory_store_parses_workflow(self):
        directory = TESTS_DIR / "workflows"
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


class TestCompositeStore:
    def test_first_hit_wins(self):
        store = CompositeStore(
            MappingStore({"pipe_x": tokenizer_module}),
            MappingStore({"pipe_x": regex_module}),
            PackageStore("tests.pyworkflows"),
        )
        assert store.load("pipe_x") is tokenizer_module
        assert store.load("pipe_x") is not regex_module
        assert store.load("absent") is None


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

    def test_list_modules_filters_by_provider(self, fixed_registry):
        pipe = _pipe_wrapper(name=_NAME, **_META)
        fixed_registry.register(ModuleDefinition(name=_NAME, sync_pipe=pipe))
        metadata = list_modules(provider="acme", show_metadata=True)

        assert list_modules(provider="acme") == [_NAME]
        assert metadata[0].provider == "acme"


def _document_resolver(directory, **kwargs) -> WorkflowResolver:
    """Builds a resolver whose document modules run through the global dispatcher."""
    resolver = WorkflowResolver(document_store=DirectoryStore(directory), **kwargs)
    resolver.register_dispatcher(dispatcher)
    return resolver


class TestResolvedDocuments:
    workflows = TESTS_DIR / "workflows"

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

    def test_document_exposes_both_interfaces(self, tmp_path):
        register_documents(tmp_path)
        interfaces = dispatcher.require_interfaces("pipe_exclaim")
        assert interfaces == frozenset({"pipe", "async_pipe"})

    def test_document_describes_dependencies(self, tmp_path):
        register_documents(tmp_path)
        context = Context(ExecutionMode.DESCRIBE_DEPENDENCIES)
        pipe = dispatcher.require("pipe_exclaim")
        assert pipe(context=context) == ["strconcat"]

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
