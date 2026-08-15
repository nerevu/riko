# Gameplan: Module Registry (P8) + Enum Discoverability (P9A)

> **Status (2026-08):** prerequisites **shipped** — P8 registry/resolver, P9A.4 value-taking chaining (`|`/`.pipe()`), P9A.1 `ModuleName` base, and decorator `isasync` inference; see [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) § P8 and [IMPLEMENTED.md](../IMPLEMENTED.md). Remaining P9A = the generated `Module` tree + introspection/stubs. (Grounding notes below predate this.)

Actionable plan derived from `_docs/current_implementation.md` (the "generated module enums"
design), scoped to **core riko only**. The `riko-microsoft` / Autopilot half of that doc is a
downstream *consumer* of this work and is planned separately (P14 — gated behind P8/P11/P12); it
appears here only as the fake in-repo example extension that proves the seam.

## Scope & resolved decisions

- **Scope:** P8 (registry/resolution seam) + **P9A** (enum + taxonomy codegen). No Microsoft code
  in `nerevu/riko`.
- **Strings stay canonical.** Enums are a typed *discovery* layer over string identifiers. JSON
  pipelines, entry points, configs, and the CLI keep using strings. Every enum member's `.value`
  **is** the canonical id; serialization always emits the value, never the member name.
- **Taxonomy is derived, not declared.** The user-facing tree category (`user_type`:
  `Sources`/`Transforms`/`Sinks`, plus provider namespaces) is computed **deterministically from
  metadata that already exists** (`ModuleMetadata.type`/`subtype`/`ftype` + provider). Built-in
  authors declare nothing new. Extensions may *override* via an explicit field. This resolves the
  conflict between the doc's `type=sources/transforms/sinks` and the shipped execution-role `type`
  (`operator`/`processor`/`splitter`) — the two are **different axes** and both are kept: runtime
  `type` unchanged; `user_type` added for codegen only.
- **No `.then()` — decision: Option C + `__or__`.** `.then()` is **rejected** (avoids a second
  chaining idiom and the `then`-means-callable semantic collision with §4 callable pipes). Instead:
  (a) **extend the existing `.pipe()`** to accept a positional `ModuleNameLike`
  (`pipe.pipe("filter", conf=...)`), and (b) add a native **`__or__`/`__ror__`** so
  `pipe | "filter"` / `pipe | Module.Transforms.FILTER` / `data | pipe` compose. Both are thin sugar
  over `_chain`, not a new object model. See [§ P9A.4](#p9a4-value-taking-chaining-pipe--__or__).
  This is the literal **`RunnableSequence (a | b)`** equivalent that
  [ai-Inference.md](ai-Inference.md) (the LangChain-replacement gameplan) maps at line 922 — and it
  stays on the pipe itself, **not** a forbidden `RikoRunnable` wrapper (that doc's key design rule).

Grounding (verified 2026-08 against the tree):
- P8 does **not** exist — it is the `⏳ next` phase. Design already lives in
  [MILESTONES.md](../MILESTONES.md) M2 (`ModuleRegistry`/`PipelineResolver`/`PipeResolver`, order
  P8.1–P8.11, file map, exit tests). **This gameplan does not restate that; it extends it.**
- Runtime catalog **exists and works**: `list_modules`/`get_module_metadata`/`gen_module_catalog`
  + `ModuleMetadata` (`riko/modules/_metadata.py`, `riko/types/modules.py`). P8 rebases these onto
  the registry; P9A reads from it.
- No enum/codegen surface exists. `riko/types/modules.py` has a stale hand-written `ModuleName`
  Literal covering ~16 of ~40 modules — P9A supersedes it.
- Chaining today is `__getattr__` (`SyncPipe("fetch").filter()`), **not** `.then()`.

---

## Phase P8 — registry + resolution seam (prerequisite)

Execute per **MILESTONES M2 order P8.1–P8.11** and its file map (`riko/ext/registry.py`,
`resolver.py`, `pipelines.py`; rebase `compile.resolve_module` + `collections` onto `PipeResolver`;
`[project.entry-points."riko.modules"]`). **Only the P9A-enabling deltas are listed here** — fold
them into P8 so the definition contract isn't reopened later.

- [ ] **P8-Δ1 — `ModuleDefinition` carries discovery metadata from day one.** When authoring
  `riko/ext/registry.py`, give `ModuleDefinition` the discovery fields the codegen needs, so P9A is
  pure read:
  ```python
  @dataclass(frozen=True, slots=True)
  class ModuleDefinition:
      name: str                      # canonical id, e.g. "fetch", "microsoft.autopilot.ensure"
      metadata: ModuleMetadata
      sync: ModuleWrapper | None = None
      async_: ModuleWrapper | None = None
      provider: str = "riko"         # "riko" for built-ins; "microsoft" etc. for extensions
      distribution: str | None = None
      distribution_version: str | None = None
      description: str | None = None
      # discoverability / codegen (all optional — derived when absent)
      enum_name: str | None = None       # override for the leaf member name
      user_type: str | None = None       # override for the tree category
      docs_url: str | None = None
  ```
  Canonical source of the id is always `definition.name`; generated enum values are never stored.
- [ ] **P8-Δ2 — registry is the single discovery source.** `list_modules`/`gen_module_catalog`
  read `ModuleRegistry` (built-ins + entry points), not pkgutil-only. (Already in the M2 file map;
  called out because P9A depends on it — codegen and `available_modules()` must see entry-point
  extensions, not just `riko/modules/*`.)
- [ ] **P8-Δ3 — provider inference for built-ins.** Built-ins register with `provider="riko"`;
  entry-point definitions supply their own `provider`. Codegen groups by provider.

**Exit (in addition to M2's P8 exit tests):** a `ModuleDefinition` round-trips its `provider` and
optional `enum_name`/`user_type`/`docs_url`; the in-repo fake example extension registers through an
entry point and appears in `list_modules()`.

---

## Phase P9A — enums + taxonomy codegen (reads P8)

Lands **immediately after P8**, ahead of the rest of P9, because the first external integration
depends on it and it stress-tests whether P8's metadata is rich enough for tooling.

### P9A.1 — normalization boundary (LANDED)
- [x] `riko/ext/names.py`: `ModuleName(StrEnum)` — a deliberately empty public base. All generated
  leaf enums subclass it (built-in and extension). Exported from `riko.ext`.
- [x] `normalize_module_name(name: ModuleNameLike | None) -> str | None` — returns `name.value` for
  a `ModuleName`, else `name` (`None`→`None`). Wired **once** in `PyPipe.__init__` (`self.name =
  normalize_module_name(name)`), the single choke point every path funnels through (direct ctor,
  `_chain`, `.pipe`/`.async_pipe`, `|`/`__or__`, `__ror__`/`_respawn`). The resolver never sees an
  enum; `self.name` is always a plain `str`.
- [x] `type ModuleNameLike = str | ModuleName` (public alias); applied to the name params on the
  ctors, `_chain`, `.pipe`/`.async_pipe`, and the collection primers. Deliberately **not**
  `str | Enum` (that would admit `Color.RED`). NB: the old `ModuleName` **Literal** in
  `types/modules.py` was renamed `ModuleId` to free the name.

### P9A.2 — deterministic `user_type` derivation
- [ ] `derive_user_type(md: ModuleMetadata, *, provider: str, override: str | None) -> str`, pure
  and total. **`user_type` categorizes by data-flow role only — the execution role
  (`operator`/`processor`/`splitter`) and its subtype vocabulary
  (`aggregator`/`composer`/`transformer`/…) are internal and MUST NOT appear in or drive the
  user-facing tree.** The user cares about "does this bring data in, change it, or send it out",
  not how the engine executes it. Precedence: explicit `override` → provider (non-`riko` → provider
  namespace) → data-flow derivation. Baseline for `provider="riko"`, using only capability signals:
  | data-flow signal (capability, not role) | `user_type` |
  |---|---|
  | produces items with no upstream input (`ftype is NONE`) | `Sources` |
  | writes/emits data outward — terminal sink (seed name-set: `output`, future `write`) | `Sinks` |
  | otherwise (consumes a stream, yields a stream) | `Transforms` |

  Notes: the three buckets are defined by **input/output behavior**, deliberately independent of the
  runtime `type`/`subtype`. `Sinks` is likely **near-empty** in core today (only the compiler-local
  `output` passthrough) — expected, not a gap. Keep the sink seed set in one named constant so it is
  auditable, and comment that the bucket is intentionally sparse.
- [ ] Unit-test the mapping against the **full** current catalog so a new module can't silently
  land in the wrong bucket (golden test over `gen_module_catalog()`).

### P9A.3 — deterministic generator
- [ ] `riko/ext/codegen.py`:
  - `enum_member_name(name: str, *, override: str | None) -> str` — uppercase; `. - /` +
    separators → `_`; collapse repeats; prefix leading digits; honor `override`.
  - **Collisions fail generation with a diagnostic** naming the two ids and telling the author to
    supply `enum_name` — never silently disambiguate.
  - `generate_module_names(defs: Iterable[ModuleDefinition]) -> str` — emits:
    - leaf `StrEnum` classes grouped by `user_type`/provider namespace (members = `NAME = "id"`),
    - namespace wrapper classes (`class Module: Sources = Sources; Transforms = Transforms; …`) so
      `Module.Sources.FETCH` **is** the same member object as `Sources.FETCH` (no duplicate defs),
    - sorted by `definition.name` (not discovery order) → byte-stable output.
  - Fixed header `# Generated by riko codegen.\n# Do not edit manually.`; **no** timestamps, paths,
    or hashes (checkable into VCS).
- [ ] Generated built-in surface written to `riko/modules/names.py`, re-exported from
  `riko/modules/__init__.py`: `Module`, `ModuleName`, `Sources`, `Transforms`, `Sinks`.
- [ ] Replace the stale `ModuleName` Literal in `riko/types/modules.py` (rename to avoid clashing
  with the new `ModuleName` StrEnum base, or delete if unused after the switch).

### P9A.4 — value-taking chaining: `.pipe(...)` + `__or__`

Enums cannot flow through the existing `__getattr__` chaining (`pipe.filter()` — the module name
*is* the attribute; you can't write `pipe.<enum>`). Two value-taking front doors fix that. **Both
funnel through the existing `_chain`; the resolver only ever sees a normalized string.** `.then()`
is explicitly not added (second idiom + `then`-vs-callable semantic clash).

- [ ] **Constructor/`_chain` normalization (foundation).** Normalize at every public boundary that
  already accepts a name string — `SyncPipe.__init__`, `AsyncPipe.__init__`, `_chain` — via
  `normalize_module_name`. After this, `SyncPipe(Module.Sources.FETCH)` ≡ `SyncPipe("fetch")`.
  Normalize **once** at the boundary; no `isinstance(x, Enum)` in the resolver.
- [x] **Option C — `.pipe(name, …)` chaining method (LANDED).** Subtlety discovered in
  implementation: `.pipe()`/`.async_pipe()` were **`SyncCollection`/`AsyncCollection`** primers, not
  `SyncPipe` methods — and `SyncPipe.__init__` set `self.pipe = resolve_module(...)` (the resolved
  module callable), so the name was occupied on pipe instances. Fix: renamed that attribute
  `self.pipe`→`self._pipe` (and `self.async_pipe`→`self._async_pipe`; fully contained in
  `collections.py`), then added a real `SyncPipe.pipe(name, **kwargs)` / `AsyncPipe.async_pipe(name,
  **kwargs)` that delegates to `_chain` (full runtime propagation). The collection primers also gained
  a positional `name`. Enum acceptance layers on later via `normalize_module_name` at the `_chain`
  boundary. (Do **not** overload `__call__` — taken by post-construction reconfig.)
- [x] **`__or__`/`__ror__` — the `RunnableSequence (a | b)` operator (LANDED, str/tuple/template +
  `__ror__`).** Native on `SyncPipe`/`AsyncPipe` (NOT a `RikoRunnable` wrapper — see
  [ai-Inference.md](ai-Inference.md) key design rule). Left-associative, single pipe per `|`
  (matches LCEL `a | b | c`). RHS dispatch:
  | `pipe | rhs` where rhs is… | behavior |
  |---|---|
  | `str` / `ModuleName` | `pipe._chain(normalize(rhs))` |
  | `(name, conf)` tuple / `(name, kwargs)` | `pipe._chain(normalize(name), **…)` |
  | a **NEW, source-less** `SyncPipe`/`AsyncPipe` template | rebind: `pipe._chain(rhs.name, conf=rhs.conf, **rhs_definitional_kwargs)` |
  | anything else | `return NotImplemented` |

  `__ror__` handles `data | pipe` (LHS is a plain iterable with no `__or__`): seed `data` as the
  source of `pipe`'s head. Guard both with `_require_usable("chain")`; a `CLOSED`/`FAILED` or
  already-consumed operand raises `PipelineStateError` (lifecycle-consistent).
  > **Deferred increment (fork):** concatenating two *multi-pipe* chains (`pipe1 | pipe2` where
  > `pipe2` is itself a chain) needs a recursive head-rebind — walk `pipe2.source` to its head and
  > reattach. Feasible (nodes retain `name`/`conf`/`kwargs`) but out of the MVP; LCEL applies one
  > runnable per `|`, so single-pipe RHS covers the motivating case.
- [ ] `describe_module`/`available_modules` (P9A.5) accept `ModuleNameLike`.

### P9A.5 — registry-backed introspection (complements, not replaces, the enum)
- [ ] `available_modules(*, type=None, subtype=None, user_type=None) -> tuple[...]` — runtime truth
  from the registry; filters accept the string *or* the taxonomy enum.
- [ ] `describe_module(name: ModuleNameLike) -> ModuleDefinition`.
- [ ] Optional taxonomy enums (`ModuleType`, per-provider subtype enums) if `available_modules`
  filtering benefits — low priority, additive.

### P9A.6 — `codegen` CLI
- [ ] `riko modules codegen` (subcommand of the `manage`/`riko` click app) → regenerates
  `riko/modules/names.py` from **built-ins + installed entry points** (excludes ephemeral runtime
  registrations by default; `--include-runtime` opt-in). Idempotent; deterministic; parallels
  `gen-config`. Add a `tests/internal` drift guard like `test_gen_config.py`.
- [ ] (Later, not P9A) aggregate `riko.generated.Module` covering the *installed environment* incl.
  extensions; `.pyi` fluent stubs — these are the rest of P9, not P9A.

---

## Exit tests (P9A)

Extend the P9 test phase (`tests/public/test_fluent_discovery.py` +
`tests/internal/test_codegen_names.py`), mirroring the doc's list:

- **generation** — built-in registry generates `Module`; deterministic ordering (by `name`);
  dotted + hyphenated names normalize; explicit `enum_name` honored; collision fails with
  diagnostic; output byte-stable across runs.
- **taxonomy** — `Module.Sources.FETCH is Sources.FETCH`; `user_type` derivation matches the golden
  map over the full catalog; provider namespace nests for the fake extension.
- **runtime** — `SyncPipe("fetch")` and `SyncPipe(Module.Sources.FETCH)` resolve identically;
  `AsyncPipe` accepts enums; the resolver only ever receives strings.
- **typing** (`tests/typing/`, P13-style) — `SyncPipe` accepts `Sources.FETCH`; rejects an
  unrelated `Enum`; plain `str` still accepted.
- **serialization** — `Module.Sources.FETCH` → `"fetch"`; pipeline JSON contains the string, never
  the member name.
- **compatibility** — every existing string-based test unchanged; raw JSON pipelines unchanged.
- **chaining** — `pipe.pipe("filter")` and `pipe | Module.Transforms.FILTER` resolve identically to
  `pipe.filter()`; `data | pipe` seeds the source; RHS type dispatch covers str/enum/tuple/template;
  a `CLOSED`/`FAILED` operand raises `PipelineStateError`; `pipe | 5` returns `NotImplemented`.

## Sequencing

1. **P8** (MILESTONES M2 order) with **P8-Δ1..Δ3** folded in.
2. **P9A.1 → P9A.2 → P9A.3** (names base → derivation → generator + built-in surface).
3. **P9A.4** (constructor/`_chain` normalization → `.pipe()` positional name → `__or__`/`__ror__`) +
   **P9A.5** (introspection).
4. **P9A.6** (codegen CLI + drift guard).
5. Prove the seam end-to-end with the in-repo fake extension (no Microsoft code).

## Doc-update checklist on landing

Per PHASE_CHECKLISTS "landing a phase" rule: tracker row + suite count; done-phase summary;
IMPLEMENTED.md as-built; add this file to the ROADMAP `## Gameplans` index; note the `ModuleName`
Literal removal in MIGRATION/CHANGES.
