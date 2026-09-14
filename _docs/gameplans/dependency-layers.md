# Dependency Layers

Riko's leaf modules (`_derive.py`, `_date_utils.py`) were carved out to break
import cycles. That is a signal that **dependency direction** is a real design
axis here, not an accident. This doc names the layers, states the boundary rules
they imply, and sketches the folder regrouping that turns those rules from
hand-maintained symbol lists into "no upward import between packages".

The rule idea is twofold: encode a few dependency-boundary checks (a small
AST/import test, not an architecture framework), and treat `collections.py` as a
shrinking compatibility facade that new execution features do not land in.

## Import kinds

Every boundary rule below is about *runtime* dependency direction, so it must
distinguish three kinds of import:

- **runtime module-scope** — a top-level `import` / `from` that executes on
  import. This is what creates cycles, and what the rules police.
- **`if TYPE_CHECKING:`** — type-only, never executed at runtime. Exempt.
- **function-local** — a deferred import inside a function body. Exempt, and for
  the ext resolver it is *required* (it is the cycle-breaker).

This distinction is load-bearing today: `types/_wrappers.py` and
`types/_resource.py` reference `context`/`resources` **only** under
`TYPE_CHECKING`, so there is no runtime cycle between the type layer and the
definition layer even though a naive scan reports edges in both directions.

## The layers

Bottom imports nothing above it. Derived from the current runtime import graph.

```text
leaf utils   _constants _formats _strutils _iterutils _importutils _logging
             _objectify _io _rssutils _serialize _reencode paths warnings
             pprint2 topsort exceptions currencies locations _date_utils
values       cast  dates  dotdict                    (coercion cluster)
bado         async backend (its own package; leaf, imported everywhere)
types        types/*  — parse-time config + wrappers
definition   context  resources  targets  (write model)
parse        parsers
runtime      _write_session  compile  collections   (collections = facade, top)
plugins      modules  ext
app          __init__ (facade)  cli
```

## The rules

All five currently hold at runtime; these are guardrails against inversion, not
fixes. Rules 1, 2, 3, and 5 are the *same* rule ("do not import from a higher
layer at runtime"); only rule 4 is a genuine exception.

| # | Rule | Formal form | Scope |
|---|---|---|---|
| 1 | types ⇏ collections | no `riko.types.*` imports `riko.collections` (and `riko.compile`, `riko._write_session`) | runtime module-scope |
| 2 | definition ⇏ execution | no `{context, resources, targets, write-model}` imports `{collections, compile, _write_session}` | runtime module-scope **and** local |
| 3 | `modules._derive` stays leaf | `modules._derive` imports only `{types.*, cast, modules._inference}` (+ stdlib); same shape for `_date_utils` (allowlist `{types}`) | any riko import |
| 4 | ext resolver ⇏ compile at module scope | `{ext._resolver, ext._pipelines}` reference `riko.compile` **only** function-locally | forbids module-scope; requires local |
| 5 | new runtime ⇏ compatibility modules | `{resources, targets, _write_session, context, write-model}` ⇏ `{collections}` | runtime module-scope |

Rule 5 needs a concrete compatibility set to be enforceable: `collections.py` is
the shrinking compatibility facade. So rule 5
reads "the write and resource runtime never imports the facade" — the correct
direction is `collections -> _write_session`, which the graph already shows —
plus the monotonic corollary: **new execution features land in runtime siblings,
never in `collections.py`.**

Collapsed, the whole set is:

> 1. A module may not import (at runtime, module scope) from a package above it
>    in `leaf < values/bado < types < definition < parse < runtime < plugins < app`.
> 2. Exception: `ext/_resolver` and `ext/_pipelines` reach `runtime.compile`
>    only via function-local imports.
>
> `cli/` is exempt from rule 1: it is the application entry point, above every
> layer, and is the one place a module-scope `import riko.compile` /
> `import riko.collections` is legitimate.

## Folder regrouping

Today the layers are correct but invisible: `context.py`, `resources.py`,
`targets.py` (definition) sit in the same flat top-level directory as
`collections.py`, `compile.py`, `_write_session.py` (execution). Grouping by
layer makes each rule a package edge instead of a symbol set. Highest payoff
first:

- **A. Extract `riko/definition/`** (`context`, `resources`, `targets`, and the
  write model). Rule 2 becomes "`definition/` must not import `runtime/`" — one
  package edge instead of two symbol sets.
- **B. Move the write model out of `types/_write.py` into `definition/`.** It is
  the write *model* (`WriteMode`/`Formats`/`WriteCapabilities`/`PreparedWrite`),
  a definition, not a parse-time config type. This is why "new runtime" and
  "definition" partially overlap `types` today; after the move `types/` is purely
  parse-time config + wrappers, tightening rule 1.
- **C. Drop the `types -> context`/`types -> resources` `TYPE_CHECKING`
  back-edges** by consolidating the Context/Resource structural type contracts
  down in `types/` (they already partly live in `types/_resource.py`) and having
  `definition/` import *down* from `types/` only. Then `types/` has zero upward
  references — the strongest form of rules 1 and 3.
- **D. Formalize a leaf tier** instead of special-casing `_derive`/`_date_utils`,
  so "leaf" is a location rather than a per-file promise.
- **E. Group execution into `riko/runtime/`** (`collections`, `compile`,
  `_write_session`), giving rule 5's corollary an obvious home and making
  `collections.py`'s facade status visible as "the top module of `runtime/`".
- **F. Leave `cli/` at the top**, exempt from rule 1.

Adopt incrementally. **A + B** carry the most rule-collapsing value with the
least churn; **C**, **D**, **E** can follow.

## Sketch: the `definition/` extraction (moves A + B)

Target tree:

```text
riko/
    types/                 parse-time config + wrappers only (no write model)
        ...
        # _write.py leaves this package
    definition/
        __init__.py        re-exports the definition surface
        context.py         (was riko/context.py)
        resources.py       (was riko/resources.py)
        targets.py         (was riko/targets.py)
        write.py           (was riko/types/_write.py)
    runtime/               (move E, later) collections / compile / _write_session
    ...
```

Import direction after the move (every arrow points *down*):

```text
runtime._write_session ─┐
runtime.collections ────┼──> definition ──> types ──> values/bado ──> leaf
runtime.compile ────────┘                     ^
                              definition.write ┘  (write model, was types/_write)
```

`definition/__init__.py` gives the layer one import surface:

```python
from riko.definition.context import Context
from riko.definition.resources import Closeable, ReusableResource
from riko.definition.targets import Formats
from riko.definition.write import PreparedWrite, WriteCapabilities, WriteMode
```

Call-site changes are mechanical rename-imports; the module *bodies* do not move
between layers:

```text
riko/context.py            -> riko/definition/context.py
riko/resources.py          -> riko/definition/resources.py
riko/targets.py            -> riko/definition/targets.py
riko/types/_write.py       -> riko/definition/write.py
```

```text
from riko.context import Context        ->  from riko.definition.context import Context
from riko.resources import ...          ->  from riko.definition.resources import ...
from riko.targets import Formats        ->  from riko.definition.targets import Formats
from riko.types._write import WriteMode ->  from riko.definition.write import WriteMode
```

Boundary constraints the extraction must preserve:

- `definition/` imports **down** into `types/`, `values`, `bado`, and leaf only —
  never `runtime` (`collections`/`compile`/`_write_session`) (rule 2).
- `runtime._write_session` keeps importing `definition.resources` /
  `definition.write` (correct direction); `definition.write` must not import back
  into `runtime` (rule 5).
- The `Formats` export enum stays a definition (a declaration), separate from the
  `Sinks` discovery bucket and from the `runtime` write execution that consumes it.
- The stable `riko` facade re-exports (`Context`, `Formats`, and the P9A
  discovery enums) are unchanged for users; only internal import paths move.

## Relationship to existing invariants

- **CLAUDE.md cross-cutting invariants** already forbid a module-scope compiler
  import in `riko/ext/` (rule 4) and describe the immutable definition layer
  (`Context`/`Resource` frozen snapshots) — this doc names the *direction* those
  live in.
- **The compatibility-facade rule** — the monotonic "no new execution in
  `collections.py`" constraint is rule 5's corollary; grouping execution under
  `runtime/` (move E) gives new features an unambiguous home away from the facade.
