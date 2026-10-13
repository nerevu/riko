# Test-suite layering gameplan

> **Scope:** owns **P13** ("public/typing/internal test split",
> [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) § P13 tracker, [MILESTONES.md](../MILESTONES.md)
> "P13"). Establishes the durable *ownership* rule for the four test layers and the concrete
> fix/remove/consolidate work to get there. The `tests/typing/{valid,invalid}/` split that P13
> also introduces is tracked in MILESTONES; this gameplan owns the *pytest/doctest* layering.
>
> **Provenance.** Audited the full test surface at a `features`-branch working state,
> commit `5c33e05` (pytest then collected `tests`, `riko`, `README.rst`, and `docs`, with both
> Python-module and `*.rst` doctests enabled). One item is **already done**: the standalone
> `tests/public/test_fluent_discovery.py` was dropped as part of P9A and its coverage folded into
> `public/test_collections.py` (since removed; `TestModuleNameEnum`) and `public/test_modules.py` — where that
> file is named below, read it as "the discovery coverage that now lives in those two files."
> Everything else in the audit still maps onto the current tree.

## 1. The ownership rule (the durable principle)

Consolidate aggressively, but **not by chasing test count**. One test owner per contract:

> **Doctests** own documented happy paths. **Public tests** own API-boundary behavior and edge
> cases. **Internal tests** own generator mechanics, drift guards, and failure modes.
> **Functional tests** own cross-layer fixture and CLI integration.

Because pytest executes doctests in Python modules, `README.rst`, and `docs/*.rst`, the
README/FAQ already exercise string-based `SyncPipe` construction and `list_modules()` filtering —
so new tests do not re-prove those string paths. The biggest net improvement is **making each
layer have one clear job**, not shrinking the suite.

## 2. Highest-priority findings (fix before deciding redundancy)

These are real test bugs — coverage that looks stronger than it is. Fix them first.

1. **`tests/functional/test_basics.py` — `_load()`/`_aload()` discard `value`/`check`.** Both
   accept `value`/`check` but hard-code the defaults when delegating:
   ```python
   def _load(self, items, pipe_name, value=0, check=1):
       ...
       _check_results(pydeps, items, pipe_name, value=0, check=1)  # ignores args
   ```
   So `self._load(items, pipe_name, 25, 0)` never verifies `< 25`/`== 25` — it always verifies the
   default `> 0`. Same bug in `_aload()`. A large part of the legacy functional suite is weaker than
   it looks. **Fix this before pruning any pipeline tests.**
2. **`tests/functional/test_pipeline.py` was not a test module** (since removed). It contains a generated
   `pipe_testpipe1()` implementation and no `test_*` functions. **Remove or relocate** it to the
   generated-pipeline fixture area.
3. **Typed module-name behavior is tested in three places** — the (now-removed)
   `test_fluent_discovery.py`, `internal/test_codegen.py`, and `TestModuleNameEnum` in
   `public/test_collections.py` (since removed). `TestModuleNameEnum` already owns normalization, constructor
   normalization, enum/string equivalence, `|`, and `.pipe()`. Discovery tests should own
   **discovery**, not generic enum acceptance.
4. **`internal/test_modules.py` has an exact behavioral duplicate.**
   `test_loop_count_all_flattens_embedded_results` and `test_loop_level_field_selects_child_input`
   invoke the same `_tokenizer_loop(... count="all", emit=True)` and expect the same output. The
   latter does not isolate the `field` behavior its name claims — give the parent both `title` and
   another candidate field so choosing `field="title"` changes the result.
5. **One resolver precedence test is ineffective.** `test_runtime_registration_shadows_entry_point`
   uses the same `marker` callable for both the entry-point definition and the runtime
   registration, so it passes regardless of which wins. Use two distinguishable callables.

## 2b. Regression batch from the branch audit

The [correctness-audit register](correctness-audit.md#8-open-defect-register--features-branch-audit)
found 17 confirmed defects in the non-module runtime, none of which fails a happy-path
test today. The register owns the *fixes*; this section owns the *coverage*, because the
register's shape is a coverage verdict: finite lists, local fixtures and file paths are
well covered, while **iterator exhaustion, unbounded sources, falsey values, nested
objects, real HTTP behaviour, binary formats, and sync/async parity** are where every
row landed.

Each of these is a **regression** test in § 6's sense — write it against the current
tree, watch it fail, then fix. They belong to the layer that owns the unit under test
(§ 1), not to one new file:

| Test | Layer | Row |
|---|---|---|
| ~~`Fetch(url, memoize=False)` returns the full body and closes the response~~ — **landed** as `tests/internal/test_io.py` (threaded local server; a fixture file cannot reach this branch) | internal | R1 |
| ~~`p(assign="x")` preserves the constructor `conf`~~ — **moved** to the split's `public/test_pipeline.py` exit tests ([MILESTONES § split](../MILESTONES.md)); writing it against the doomed `PyPipe.__call__` only pins an API being deleted | public | R2 |
| ~~keyed `join(count(), finite_other)` yields a first result~~ — **landed** as `tests/public/test_modules.py` (keyed **and** natural; asserts bounded consumption, since the operator wrapper reads one item ahead) | public | R3 |
| `async_pipe` (`send`) yields its first item before the source is exhausted | public | R4 |
| `compile_workflow` handles ids `"class"`, `"foo bar"`, `"foo.bar"`, `"1st"`, `"café"` | internal | R5 |
| ~~an unsupported object **nested** in a dict/list arg bypasses `repr_cache` and reaches the function unchanged~~ — **landed** as `tests/internal/test_values.py::TestReprCache`; fixed by propagating `_UNSUPPORTED` in `_to_hashable` (correctness-audit R6) | internal | R6 |
| ~~`gather_results([none(), one(), none()])` preserves all three positions~~ — **landed** as `tests/internal/test_io.py::TestGatherResults::test_gather_results_preserves_none_positions`; the defect was fixed with the `MISSING` sentinel (correctness-audit R7) | internal | R7 |
| ~~`Reencoder.read(1)` returns one character and the remainder survives the next `read`~~ — **landed** as `tests/internal/test_io.py::TestReencode::test_char_count_preserves_remainder`; fixed with a char/byte remainder buffer (correctness-audit R8) | internal | R8 |
| `fetchtable` reads a real `.xlsx` and `.sqlite` fixture, sync **and** async | functional | R9 |
| `fetchdata` detects the format of `…/export.json?token=x` | internal | R10 |
| ~~a tz-aware `struct_time` (`+03:00`) produces the matching epoch~~ — **landed** as `tests/internal/test_values.py::TestDates`; `utime` now builds an aware datetime + `.timestamp()` (correctness-audit R11, utime half) | internal | R11 |
| ~~`get_skip({"content": "none available"}, {"field": "content"})` follows field-presence semantics~~ — **landed** in `tests/internal/test_values.py::TestParsers`; absent `text` no longer coerced to `"None"` (correctness-audit R12) | internal | R12 |
| ~~`listize=True` turns `0`/`False`/`""` into one-element lists~~ — **landed** as `tests/internal/test_modules.py::TestPrepare`; `build_conf` branches on the option, not truthiness (correctness-audit R13) | internal | R13 |
| a stalled async iterator is actually interrupted by `timeout` | internal | R14 |
| the same bytes decode identically across sync HTTP, async HTTP and async local file | functional | R15 |
| ~~`has_header=False` closes the original source as well as the spool~~ — **landed** as `tests/internal/test_io.py::TestFetch::test_csv_headerless_closes_original_source` (spies the original's `close`, cross-version); fix predated this via the variadic `auto_close` (correctness-audit R16) | internal | R16 |

Both open-question rows are now resolved. R19 (`filter`'s `greater`/`less` over strings) was
**decided** in favour of type-aware comparison — numeric when both operands coerce to a number,
else lexicographic — so its characterization test was *updated, not deleted*, into a regression.
R17 (`parse_dag` on an empty module list, not reproduced) landed as a **strict-xfail tripwire** —
the divergent empty-input handling (full-def `IndexError` vs DAG silent output-only) was a gap
deferred to the Workflow v2 normalization boundary
([extensibility § E3](extensibility.md#e3-canonical-workflow-v2-specification)), not accepted
behaviour to pin. That boundary landed at cutover step 3 (2026-09-29): the `PipeDag` reader (now `Workflow.parse`)
rejects an empty DAG with `InvalidPipelineError`, the tripwire is retired, and
`tests/public/test_workflow.py::TestPipeDag::test_empty_modules_raise_invalid_pipeline` guards it.

## 3. Layout and enforcement

The suite is laid out so that placing a test is a lookup, not a judgment. The rules live in the
test folders themselves — this gameplan does not restate them:

- `tests/__init__.py` (docstring) — the two-step placement rule (tier first: functional, then public,
  then internal; then the subject's row), the in-file layout (every test in a `Test<Subject>` class,
  async twin after its sync class, behaviors → rejection tables → strict-xfail tripwires), and the
  size triggers (split a file past ~2000 lines by moving its largest row out; merge one under ~300).
- `tests/<tier>/__init__.py` (docstring) — that tier's index: one row per file naming the subjects it
  owns. Files start coarse (3 public, 8 internal, 2 functional) and split only when unwieldy. Files
  are named for stable concepts, never mirrored from `riko/` package paths, so package refactors
  move imports, not tests.
- Shared helpers live in `tests/_*.py` (`_lifecycle`, `_execution`, `_workflows`, `_loopback`,
  `_timeouts`); no helper is defined in two test files.

Enforcement:

- `manage lint --tests` (in `--all`, `riko/cli/_lint_tests.py`) fails on an unindexed or missing
  file, a subject on two rows, a top-level `test_*` function, a `Test*` class whose subject is not on
  its row, a private name imported in `public/`, a history-named file (`test_regressions`), a helper
  module inside a tier, or a stray folder; it prints size advice without failing.
- Ruff `ERA` (commented-out code) is enforced for `tests/` (generated `pyworkflows` excepted).
- `manage lint --docs` fails on a backticked `tests/<tier>/test_*.py` citation in a tracked
  `_docs/` root doc, a gameplan, `CONTRIBUTING.rst`, `CLAUDE.md`, or `docs/*.rst` that names no
  current file; a line saying the file was deleted, retired, removed, dropped, merged, or
  superseded records history and is exempt. Repoint a moved test's citations when moving it.
- `manage test --ratchet` fails when the full suite leaves more statements uncovered than
  `[tool.riko.coverage] uncovered` in `pyproject.toml`, and lowers that ceiling on a gain. The
  ceiling counts uncovered lines rather than a percentage, so losing coverage of existing code and
  adding untested code both fail it while deleting code never does. It is measured in the full dev
  environment (Python 3.12, all extras); `/land` and that CI leg run it. Dev-only `manage`
  tooling is omitted (`[tool.coverage.run] omit`), and the console scripts count through their
  subprocess runs (`patch = ["subprocess"]`); a new `manage` helper module joins the omit list.
- `/tidy` § 3.9 asks the judgment questions the lint cannot: right tier and row, and whether a
  doctest or existing test already owns the case.

Pending: `manage lint --tests` bans only `_private` names in `public/`. The fuller placement rule
— a public test uses only supported names — would check `public/` imports against
`riko/base/_api_surface.py`; the `public/` files' imports of non-surface modules need moving or an
allowlist first.

### Import-linter coverage gap

`tests/internal/test_cli.py` does not yet cover: descendants, keyed topsort, frozen
graph; an exact bare `TYPE_CHECKING` (`typing.TYPE_CHECKING` is not exempt, `else` is
runtime); `from . import _private` and mixed multi-target imports; transitive permission and
forbidden direction; enforced local imports; same-layer private allowed / public forbidden; a
type-only graph recorded but not violated; dangling/cyclic/redundant architecture declarations;
deterministic diagnostics; exit codes (analysis error → 2, violation → 1, clean → 0); complete
`ArchitectureReport` rendering.

### Discovery coverage

Discovery is owned by `public/test_modules.py` (`TestListModules`, `TestDescribeModule`) and the
`ModuleName` enum by `public/test_pipeline.py` (`TestModuleNameEnum`). Prove the enum crosses the
pipe boundary with a deterministic module rather than comparing `.name`; keep the graceful
`describe_module(unknown) is None` edge; do not add assertions that only test `StrEnum` behavior.

## 4. Doctest audit

Different deletion rule from pytest, because doctests are executable documentation:

- **Public/built-in doctests stay** when they demonstrate a useful API behavior — overlap between a
  README journey and a module example is not inherently wasteful. One module-level example is a
  soft default, not a cap: keep a second example when it demonstrates a distinct first-class mode
  or completes the module's primary workflow.
- **Deleting a module example requires an ownership check.** First look for equivalent function/class
  doctests and pytest coverage. Move genuinely uncovered behavior to the appropriate test before
  deleting the example; do not create a duplicate pytest test when another doctest already owns it.
  If the example is later restored, remove a pytest test that exists only as its duplicate.
- **Private doctests need stronger justification.** If `_inference`/`_iterutils`/`_objectify` already
  have focused pytest coverage, move edge cases to pytest and leave at most a tiny descriptive
  example. `_inference.infer_from_source()` is the clearest candidate — its doctests repeat pytest
  cases.
- **The root `riko/__init__.py` doctest should go.** It re-teaches a normal `SyncPipe` workflow the
  README/module docs already own. The package initializer should describe the namespace's purpose,
  audience, stability, and package-wide semantics instead. This exception removes the requirement
  for a package example; it does not permit collapsing a public package docstring to a vague label.
- **FAQ doctests should own ordinary discovery examples** (`list_modules()` ordering/type/loopable/
  subtype/primary/metadata/export targets) — which is *why* several simple `public/test_modules.py`
  assertions can disappear. Once typed discovery is documented there, add `Modules.Sources`,
  `list_modules`, and `describe_module` happy paths to the FAQ.
- **`docs/INSTALLATION.rst`** doctest is worth keeping: a self-contained "imports + basic chaining"
  installation smoke test.
- In sync-only environments `conftest.py` skips Async/Bado doctest items whole and skips the
  individual `run(...)` examples of every other doctest (`.rst` files included). Do not add
  `issync` branches solely as doctest fallbacks; write the real async example and let collection
  policy handle unavailable optional support.
- `>>>` in `examples/**`, `_docs/**`, and `CLAUDE.md` are **not** collected today — which is exactly
  why `functional/test_script.py`'s `TestExamplePipelines` matters: it is what actually executes the
  example pipelines.

## 5. First-pass patch (conservative, mostly indisputable)

```text
FIX
- test_basics._load/_aload forward value/check correctly
- resolver precedence tests use distinguishable implementations
- loop field-selection test actually isolates field selection
- test_script output helper stops carrying ineffective comparison logic

REMOVE
- tests/functional/test_pipeline.py
- test_codegen_names::test_member_is_shared_object
- 2 redundant test_gen_config structural tests
- test_loop::test_loop_has_async_pipe
- one duplicate loop count/field test after rewriting the useful one
- test_sync_async_parity::TestLifecycleObservableParity
- redundant import-surface assertions
- private _inference doctests duplicated by test_inference

CONSOLIDATE
- augment_entries fallback tests
- sync/async Kazeeki expectations
- simple example pipelines
- DotDict deletion matrix
- codegen taxonomy tests
- export-surface tests
- ModuleName tests into one owner
```

**Do not** reduce `test_compile`, `test_parallel`, `test_streams`, or the core lifecycle tests just
to shrink the suite — they cover contracts hard to catch elsewhere.

**Shipped (first-pass patch).** The conservative FIX/REMOVE set has landed:

- `test_basics._load`/`_aload` now forward `value`/`check`; the two stale expected counts the
  live assertions exposed were corrected to the deterministic fixture truth (`feeddiscovery`
  25→15, `simplemath_1` 4→6).
- Resolver precedence tests use distinguishable callables: `test_runtime_registration_shadows_entry_point`
  now proves the runtime marker (not the entry-point one) wins, and `test_composite_store_first_hit_wins`
  puts a different object in the first two stores so it proves precedence, not fallback.
- `test_loop_level_field_selects_child_input` now isolates `field` (a parent carrying both
  `title` and `alt`, tokenizing on `alt`), so it is no longer a duplicate of
  `test_loop_count_all_flattens_embedded_results`.
- `test_script.assert_output_matches` dropped the dead/broken `bool` branch and the
  `SequenceMatcher` `partial` path; `test_benchmark` now asserts the stable benchmark labels
  directly (each label heads a line, robust to the right-justified name padding).
- Removed `test_loop_has_async_pipe`, `TestLifecycleObservableParity` (both engines already
  covered in `test_pipe_lifecycle.py`), and the two redundant `test_gen_config` structural tests
  (byte equality subsumes them).
- Trimmed `_inference.infer_from_source` doctests to one descriptive example; the map/sum/unknown
  edge cases live in `test_inference.py`.

**Shipped (§ 3 consolidation, first batch).**

- `test_dotdict.py` — nine deletion tests folded into one parametrized `(source, key, expected)`
  matrix (root/nested/deep, case variation, missing paths), one case per `pytest.param` id.
- `test_codegen_names.py` — the three taxonomy partition tests collapsed into a single golden
  partition (`test_taxonomy_partition_matches_golden`); the enum override case folded into the
  `test_enum_member_name` parametrization; the two provider tests now **execute** the generated
  source (`exec`) and assert on the resulting enum objects instead of string-searching it.
- `test_decorators.py` — dropped `test_lambda_infers_sync_without_isasync`/
  `test_lambda_needs_explicit_isasync` (duplicates of `TestIsasyncInferenceValid` rows); the
  class now owns only the end-to-end async-execution proof.
- `public/test_modules.py` split public↔internal: exact metadata derivation
  (`get_module_metadata` classification) + the `@operator` subtype inference moved to the new
  `internal/test_modules.py`; the public file now owns only discovery-filtering combinations,
  API errors, and input test-flag scoping. (Internal tests import from defining modules per the
  established convention — not the `riko` facade.)
- `public/test_collections.py` (since removed) deduped: the sync/async copies of
  `test_pipes_use_loopability_for_mapping` folded into one `_ENGINES`-parametrized parity test,
  and the redundant `test_enum_and_string_resolve_identically` dropped (equivalence is already
  proven by `test_resolve_module_name` + `test_constructor_stores_plain_string`).
- `internal/test_modules.py`: dropped the facade-level `test_register_requires_name` (the
  registry-level `test_runtime_register_requires_name` already owns the `"needs a name"`
  validation; the facade just forwards, and its delegation is covered by
  `test_register_resolves_via_facade`), and renamed the misleading
  `test_pipeline_delegates_to_compiler` → `test_non_stored_workflow_name_routes_to_module_registry`
  (it proves a plain name routes to the module registry, surfacing `UnsupportedModuleError`).
- `functional/test_basics.py`: the identical `fetchpage`/`fetchpage_loop` tests folded into one
  parametrized `test_fetchpage` (`plain`/`within-loop` ids) — they assert the same output.
- `internal/test_modules.py` consolidated: the homogeneous classification tests folded into a
  single `test_classification` `(pipe, kind, source)` matrix (module-level pipe fixtures; `source`
  asserted only where the originals did, via an `_ANY` sentinel — no new claims), and the three
  UNKNOWN-with-reason tests into one `test_unknown_with_reason` `(pipe, reasons)` matrix. Multi-kind,
  decorator-unwrap, `infer_from_source`, and `gen_operator_return_kinds` cases kept as distinct
  owners.
- `functional/` layering: the three direct `augment_entries` unit tests moved to the new
  `internal/test_rssutils.py` (since merged; parametrized fallback matrix), the mocked `_io` backend test moved
  to `internal/test_io.py` (whose loopback-server tests are now grouped under a
  `simulated_network`-marked class so the mock test isn't mislabeled), the sync/async Kazeeki
  expected payloads shared via module constants + a `_assert_kazeeki` helper, and the four
  single-item example pipelines (`simple1`/`simple2`/`split`/`wired`) folded into one
  `test_simple_pipeline` parametrization.
- `public/test_modules.py` (the P13 exit test) consolidated **without weakening the contract**:
  the two per-name `hasattr` parametrizations collapsed into one single-assertion resolve check
  each (stable + extension); `test_no_private_names_in_public_all` removed and its guarantee folded
  into `test_partial_surface_matches_expected` (equal surfaces already get no-private free from
  golden-set equality; the partial `riko.modules`/`riko.exceptions` surfaces now assert it
  explicitly — and the modules check now also covers `riko.modules._names`); and
  `test_no_leaked_public_functions`'s overclaiming docstring corrected to state it guards
  *functions* specifically (classes/constants like `Context` are intentionally unexported).

**Not done, by design.** Two § 3 suggestions were assessed and **declined** as coverage-losing:

- *Trim `test_collections.py` chaining tests as "README doctests already own hash basics."* README
  covers `.hash()` and `| Transforms.HASH` (the **enum** form) only — it does **not** exercise the
  **string** forms (`| "hash"`, `.pipe("hash")`) or their source-binding semantics, which those
  chaining tests specifically own. Trimming them would drop real coverage, so they stay.
- *Trim the `TestExamplePipelines` `gigs`/`kazeeki` exact records to smoke contracts.* The full-record
  assertions are the only exact check of the example entry-point output; smoke-trimming loses that.

The deeper `test_collections.py` split into focused files is not warranted either — the audit
detail says "keep TestModuleNameEnum / pub-sub identity+cleanup / pool ownership **here**", i.e. the
concern is dedupe (done), not file fragmentation.

**Shipped (§ 2b regression batch).** The local-repair rows (R6/R7/R8/R11/R12/R13/R16) are fixed
with regressions verified failing-first (see the [correctness-audit register](correctness-audit.md#8-open-defect-register--features-branch-audit)
for per-row detail). The remaining rows are owned by other gameplans, so each landed as a **strict
xfail tripwire** — it asserts the future-correct behavior, fails today, and flips to XPASS (failing
the suite, forcing the marker's removal) the moment its owner lands:

- **R5** — `tests/internal/test_codegen.py::TestPythonise::test_pythonise_yields_valid_identifiers` (module-enums.md;
  re-homed from the deleted `test_compile.py` at v1-cutover step 5, 2026-10-03).
- **R9** — `tests/functional/test_basics.py::test_fetchtable_reads_sqlite_fixture` — the sqlite half
  proves the binary-as-text defect (no xlsx writer in the env; the xlsx and async halves stay owned)
  (connectors.md).
- **R10** — `tests/public/test_modules.py::TestExtensionlessFetchdata::test_query_string_does_not_defeat_extension`
  (connectors.md).
- **R14** — `tests/internal/test_io.py::TestAsyncTimeoutIterator::test_timeout_interrupts_a_stalled_source`, asserting
  elapsed rather than content (content is unchanged across the fix) (execution-semantics.md § 7.2).
- **R15** — `tests/internal/test_io.py::TestAsyncUrlOpen::test_async_url_open_honors_content_type_charset` — the
  async-HTTP charset half (the `async_url_read`/`fetchpage` halves stay owned) (bado-anyio § 2c).
  `tests/internal/test_io.py::TestAsyncUrlOpen::test_sync_and_async_decode_line_endings_alike` is the line-ending
  half: sync and async must decode `b"abc\rdef\n"` alike (bado-anyio § 2c).
- **R18** — `tests/internal/test_modules.py::TestResolverDispatcher::test_runtime_registered_pipe_prefixed_module_resolves`
  (extensibility § 24).
- **R17** — `tests/internal/test_compile.py::test_convert_dag_empty_modules_raises` (since retired) asserts that
  `parse_dag({"modules": []})` raises is **retired**. It does *not* today — the terminal `output` node is appended
  unconditionally, so an empty DAG silently yields `{_OUTPUT}` (the reported `module_ids[-1]` crash is
  *not reproduced* on this path; only the full-pipe-def path raises, via `MALFORMED["empty"]`). A clean
  typed rejection + one validation front-door that makes both paths reject identically is owned by the
  **Workflow v2 spec** ([extensibility § E3](extensibility.md#e3-canonical-workflow-v2-specification) —
  the E3.1 `normalize_workflow() -> validate` boundary; CLI surface: cli.md `riko pipeline validate`);
  recalibrate the tripwire from `IndexError` to the spec's error when it lands. The topology both paths
  share is now the immutable `GraphIndex` built by `Workflow.index` — the structural seam that
  front-door validates over ([E3.11](extensibility.md#e311-reuse-of-the-shipped-graph-index)).
  **Resolved at cutover step 3 (2026-09-29):** the bare-bones DAG (`PipeDag`) reader is now `Workflow.parse`, which
  routes through that canonical `normalize_workflow` → `validate` front door, so an empty DAG raises
  `InvalidPipelineError("workflow has no nodes")` — the same rejection the full-document path gives.
  The tripwire is **retired**; the behavior is guarded by the regular test
  `tests/public/test_workflow.py::TestPipeDag::test_empty_modules_raise_invalid_pipeline`.

**Shipped (§ 2b open-question rows).** R19's characterization test was **updated, not deleted**, into
a regression once the contract was decided (type-aware comparison):

- **R19** — `tests/public/test_modules.py::TestFilter::test_filter_greater_less_compare_numeric_strings_numerically`
  asserts that `filter`'s `greater`/`less` compare numeric strings numerically (`"10" > "9"`) and fall
  back to lexicographic comparison for non-numeric strings (correctness-audit R19, now fixed).

**Remaining.** None — the § 2b regression batch is complete (local repairs fixed, owned rows guarded
by strict-xfail tripwires).

**Shipped (second pass, 2026-10-13).** The suite is 13 indexed subject files (3 public, 8 internal,
2 functional) with `Test<Subject>` classes and shared `tests/_*.py` helpers; duplicate cases and
copy-paste families are gone (each deletion names its covering owner); the § 3 enforcement is in
place, with the uncovered-line ceiling recorded at 584.

## 5b. Execution lifetime proofs (R4)

`implementation-sequence.md` R4 adds a proof obligation that does not fit the existing file map, so
name its owner now: **functional tests** own the external-resource lifecycle proof, because it needs
a real client rather than a fixture double.

The matrix is small and deliberately non-negotiable — two resource kinds crossed with two execution
modes:

| | sync Pipeline execution | async Pipeline execution |
|---|---|---|
| `@contextmanager` sync resource | native entry | worker-adapted entry |
| `@asynccontextmanager` async resource | portal entry | native entry |

Each cell proves eager open, lazy open, mid-execution failure rollback, early consumer abandonment,
cancellation, and `ExceptionGroup` grouping of multiple cleanup errors.

Two internal drift guards accompany it:

- no execution-spawned task escapes the execution's task group (assert no surviving tasks after
  teardown, including on the cancellation and abandonment paths);
- no module, parser, factory, or extension code constructs an event loop, portal, executor, worker
  thread, or task group. A grep-style guard over `riko/` outside `riko/_execution/` is adequate and
  cheap.

Both guards belong in `tests/internal/`, since they are drift guards rather than API behavior.

## 5c. Write-session coverage (shipped)

The write-session architecture (see [IMPLEMENTED.md § Write sessions](../IMPLEMENTED.md#write-sessions--private-seam-awaiting-writenode)) ships
with its behavior proven in two files, laid out by the same ownership rule as § 1:

- `tests/internal/test_definitions.py` — the capability model (`appendable` derives from `modes`,
  `serializes` from a resolved `fmt`, `keyed_modes` is the union of both keyed sets, match/idempotent
  sets never overlap and stay subsets of `modes`; `File × {CSV, JSONL, JSON}` rows; the
  key-validation matrix) and session behavior (one converter call on the whole-stream path,
  per-item passthrough; CSV header/schema/append boundaries; JSONL one value per line with one final
  terminator; framed JSON/GeoJSON stage-then-publish-once with abort discarding the staged document;
  the `_SessionState` transitions and misuse).
- `tests/public/test_pipeline.py` — the public surface: `write()` passthrough yields each input once,
  `sink()` returns a `WriteResult` for both sync and async, and the async error text carries no
  pub/sub language; the pending `Pipeline.write` tripwires sit beside them.

For incremental formats these tests deliberately do **not** assert rollback of already-written bytes.
When R4B/R5C take over session-lifetime ownership, they reuse this same contract rather than
re-proving it.

## 6. Relationship to the P-track

- **P13 exit tests** (see [MILESTONES.md](../MILESTONES.md)) — `public/test_modules.py` (extended
  public/EXT `__all__`; no accidental internal exports) + `tests/typing/`. This gameplan supplies the
  *layering* half of P13; the `tests/typing/{valid,invalid}/` type-check split is MILESTONES' half.
- **Live status** (done/next/suite count) lives only in the
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) tracker — do not restate it here.

## 7. Operations as Code and cross-package test ownership

Operations as Code adds cross-package scenarios but **does not change the one-test-owner rule**.
Tests follow the contract owner rather than being copied into every package that participates:

| Concern | Test owner |
|---|---|
| `OperationSpec`, `OperationPlan`, reproducibility, overlays, import provenance/lossiness, `CompatibilityReport`, deployment drift | `operations-as-code.md` / `riko-ops` |
| provider-native asset discovery/acquisition/export/deployment/inspection and target compatibility facts | `provider-integrations.md` / provider package |
| common capability discovery/catalog/policy/approval | `mcp.md` / `riko-mcp` |
| provider `OperationHandle` waiting | `provider-integrations.md` |
| Microsoft `ChangePlan`/desired-state/apply/verify | `microsoft-administration.md` / `riko-microsoft` |
| durable scheduler/runner phase boundaries | `orchestration.md` / orchestration adapter package |
| operation command parsing/rendering/exit codes | `cli.md` / `riko-cli` |
| Pipeline/runtime/state/idempotency mechanics used underneath | existing Core public/internal owners |

Do not create a giant duplicated "Operations as Code" test suite inside Core. Cross-package
functional fixtures should prove composition while each semantic assertion remains concentrated in
its owning package.

Two architecture fixtures are required once the corresponding adapters exist:

### SuperOps script → GitHub Actions

A functional fixture should prove the composition:

```text
provider discovery/acquisition
→ preserved source artifact/provenance
→ normalized OperationSpec
→ shared capability discovery
→ CompatibilityReport
→ target deployment
→ target inspection
→ automation-drift comparison
```

The provider fixture owns extraction/deployment facts; `riko-ops` owns normalization, compatibility,
and drift assertions; CLI tests, if any, only prove command adaptation. The fixture must include at
least one target-specific semantic that is flagged as adaptation/manual/unsupported so the test does
not accidentally assert universal portability.

### Windows Autopilot approval + long provider wait

A functional fixture should prove:

```text
OperationSpec
→ Microsoft ChangePlan
→ OperationPlan containing the ChangePlan fingerprint
→ human/policy approval
→ apply
→ OperationHandle
→ wait_operation
→ authoritative Microsoft verification
→ operation verification/evidence
```

The test must invalidate approval when the nested `ChangePlan` changes and must prove that long
waiting still uses provider `OperationHandle` semantics even if orchestration persists/resumes the
handle across a run boundary.

These fixtures should use deterministic fake providers/runners until live integration tests are
explicitly enabled. Secrets, tenant IDs, remote script contents, and unredacted imported values do
not belong in snapshots/golden files.

Implementation scaffolding should add tests in the same order as the corresponding owners land:
provider hooks → operations services → orchestration/CLI adapters → cross-package fixtures. The
`testing.md` layer rules remain unchanged; Operations as Code is another consumer of them, not a
fifth test layer.
