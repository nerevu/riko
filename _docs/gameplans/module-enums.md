# Module registry & enum discoverability gameplan

> **Shipped (P9A.1–P9A.6; targeted for release v0.76.0):** the
> `ModuleName` base + `normalize_module_name`, `derive_category` taxonomy, the
> `riko.ext.codegen` generator + committed `riko/modules/_names.py` (the flat `Modules`
> namespace + `Sources`/`Transforms`/`Sinks` buckets), value-taking `|`/`.pipe()` chaining,
> `list_modules`/`describe_module` introspection, and the `gen-names` CLI + drift guard. The
> discovery tree is re-exported from the **stable `riko`** surface (not `riko.modules`,
> whose `Module` already names the decorator base — the wrapper was named **`Modules`** (plural)
> to sidestep that collision). As-built detail: [IMPLEMENTED.md §24](../IMPLEMENTED.md#24-module-discovery-shipped);
> status: [PHASE_CHECKLISTS.md § P9A](../PHASE_CHECKLISTS.md).

Design record for the "generated module enums" work, scoped to **core riko only**. The
`riko-microsoft` / Autopilot half is a downstream *consumer* of this work, owned by
[autopilot-provisioning.md](autopilot-provisioning.md) and planned separately (P14 — gated behind
P8/P11/P12); it appears here only as the fake in-repo example extension that proves the seam.

## Scope & resolved decisions

- **Scope:** P8 (registry/resolution seam) + **P9A** (enum + taxonomy codegen). No Microsoft code
  in `nerevu/riko`.
- **Strings stay canonical.** Enums are a typed *discovery* layer over string identifiers. JSON
  pipelines, entry points, configs, and the CLI keep using strings. Every enum member's `.value`
  **is** the canonical id; serialization always emits the value, never the member name.
- **Taxonomy is derived, not declared.** The user-facing tree category (`category`:
  `Sources`/`Transforms`/`Sinks`, plus provider namespaces) is computed **deterministically from
  metadata that already exists** (`ModuleMetadata.type`/`subtype`/`ftype` + provider). Built-in
  authors declare nothing new. Extensions may *override* via an explicit field. The runtime
  execution-role `type` (`operator`/`processor`/`splitter`) and the data-flow `category` are
  **different axes** and both are kept: runtime `type` unchanged; `category` added for codegen only.
- **No `.then()` — decision: Option C + `__or__`.** `.then()` is **rejected** (avoids a second
  chaining idiom and the `then`-means-callable semantic collision with §4 callable pipes). Instead:
  (a) **extend the existing `.pipe()`** to accept a positional `ModuleNameLike`
  (`pipe.pipe("filter", conf=...)`), and (b) add a native **`__or__`/`__ror__`** so
  `pipe | "filter"` / `pipe | Transforms.FILTER` / `data | pipe` compose. Both are thin sugar
  over `_chain`, not a new object model. This is the literal **`RunnableSequence (a | b)`**
  equivalent that [ai-inference.md](ai-inference.md) (the LangChain-replacement gameplan) maps —
  and it stays on the pipe itself, **not** a forbidden `RikoRunnable` wrapper (that doc's key
  design rule).

## Remaining work

### One identifier sanitizer (R5)

Two normalizers exist and only one works. `ext/codegen.py`'s `enum_member_name` collapses
every run of non-alphanumerics and guards a leading digit; `compile.py`'s `pythonise`
replaces four characters (`-`, `:`, `/`, `""`) and ASCII-`replace`-encodes, so
`"class"`, `"my module"`, `"foo.bar"`, `"1st"` and `"café"` all reach generated source as
identifiers — a pipeline that runs fine through `build_pipeline` can emit source that
does not parse ([correctness-audit **R5**](correctness-audit.md#8-open-defect-register--features-branch-audit),
the `C6` "weaker duplicate" shape).

- One sanitizer in `ext/codegen.py` — the module that already owns generated-source
  formatting (`ruff_format`) — handling non-alphanumerics, leading digits, **`keyword.iskeyword`**,
  and collisions (suffix, deterministically); `enum_member_name` becomes the upper-case
  caller, `pythonise` the identifier caller.
- `stringify_pipe` emits the sanitized id as the variable while the `PipeDef`/JSON keeps
  the original string — ids stay canonical (§ Scope), exactly as enum `.value` does.
- Round-trip test over the pathological ids above, plus the existing
  `test_codegen_matches_expected_file` byte guard to prove no `tests/pypipelines/*.py`
  output changes.

This is additive and gates nothing; sequence it with whichever of the two generators is next
touched.

### Installed-environment aggregate + stubs

- aggregate `riko.generated.Modules` covering the *installed* environment incl. entry-point
  extensions (the committed `riko/modules/_names.py` stays built-ins only, keeping the drift guard
  env-stable).
- `.pyi` fluent stubs.
- Optional taxonomy enums (`ModuleType`, per-provider subtype enums) if `list_modules` filtering
  benefits — low priority, additive; string/`StrEnum` filters suffice today.

### Deferred increment — multi-pipe `|` concatenation

Concatenating two *multi-pipe* chains (`pipe1 | pipe2` where `pipe2` is itself a chain) needs a
recursive head-rebind — walk `pipe2.source` to its head and reattach. Feasible (nodes retain
`name`/`conf`/`kwargs`) but out of the shipped MVP; LCEL applies one runnable per `|`, so the
shipped single-pipe RHS covers the motivating case.
