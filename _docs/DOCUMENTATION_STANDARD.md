# riko documentation standard

The authoritative rules for docstrings, doctests, and `__init__.py` in this repo.
When normalizing documentation, follow this guide rather than copying neighboring
legacy docstrings verbatim — many existing docstrings are inherited technical debt.

> **Types define structure. API tier determines audience. Docstrings define
> semantics and contracts. Doctests demonstrate real behavior. Private
> documentation preserves non-obvious implementation knowledge.**

## Prerequisite: annotations own types

Every function, method, property, callback, and return value is fully typed.
Type annotations are the source of truth for types. **Never** encode types in
docstring parameter/return labels.

```text
Bad:   count_key (str): Field to count by.
Good:  count_key: Field to count by.
```

Do not use `mixed:` / `Awaitable:` / `Deferred:` return labels, and do not name a
parameter in the docstring that differs from the signature.

### Exception: values consumed from an untyped `**kwargs` keep their type labels

The rule above assumes annotations that describe the call. Every module's
`pipe`/`async_pipe` is declared `(*args: Any, **kwargs: object)` — annotations
that describe nothing. There the docstring is the *only* record of the contract,
so it carries the types as well as the names.

The same holds for any individual option a function pulls out of an untyped
`**kwargs: object` (e.g. an `emit` flag read via `kwargs.pop("emit", ...)`):
the signature annotation covers the whole bag, not that key, so document it in a
`Kwargs:` section with its type label (`emit (bool): …`). A parameter that has
its own real annotation stays typeless — `parser` / `async_parser`
(`stream: Stream, objconf: WriteObjconf, tuples: PipeTuples`) carry no labels.

`conf` also keeps its nesting: its keys are entries inside a dict argument, not
parameters in their own right. Flattening them is a factual error — it tells the
reader to call `pipe(stream, count_key="word")`, which is not the signature.

```python
    Args:
        items (Items): The input stream.
        conf (dict): The module configuration.

            count_key (str): Field to count by. Groups items in the stream by
                the given key and reports a count for each group.

        context (Context): the run environment

    Kwargs:
        assign (str): Field the count is assigned to. Ignored when ``count_key``
            is set (each group's value names its count instead) or ``emit`` is True
            (default: "count").
        emit (bool): Whether to emit the count directly rather than assigning
            it. Overrides ``assign`` (default: False).
```

The source parameter differs by wrapper type:

| Wrapper | Label | Because |
|---|---|---|
| `operator` / `splitter` | `items (Items)` | the input *is* the stream |
| `processor` | `item (Item \| Items)` | one item, or an iterable mapped element-by-element |

A processor's first argument is overloaded — one item, or many — and the wrapper
decides via `is_listlike(item)`, mirroring `listize`'s boundary: a `list`,
`tuple`, `range`, generator or iterator maps over each element, while a mapping,
primitive, string or `None` is a single item (so `None` still invokes source
modules). Only the outermost argument is interpreted that way, so a list-valued
*field* inside an item stays one value.

Explain it once — the FAQ's *"How does a processor map over items?"* — and have
the module keep a one-liner pointing there rather than repeating the rationale
in all ~30 processors.

Document only the **user-facing** keyword arguments: `conf`, `context`, and the
call options `assign`, `emit`, and `field` where the module actually uses them.
Omit the decoration options — `ftype`, `ptype`, `extract`, `listize`, `objectify`
— which are set once in the module's `OPTS` at decoration time and are not part
of the pipeline author's surface. The full keyword-argument table lives once in
`docs/FAQ.rst`; don't restate it per module.

When converting a legacy `Kwargs:` block, preserve every name and the
indentation that shows what nests under `conf`. Cross-check against the
function's own doctests: if an example calls
`pipe(stream, conf={"count_key": "word"})`, then `count_key` belongs under
`conf`.

### The two returns of a pipe callable

A `pipe` has two distinct "returns", and they belong in different places.

| | Describes | Audience |
|---|---|---|
| Return **annotation** | what the *undecorated* function returns, pre-wrapper | `_derive_operator_subtypes` |
| **`Yields:`** section | what the *caller* gets — always a stream | users |

The annotation is load-bearing metadata, not documentation. `_derive.py` reads
it off the undecorated function and classifies the module from it: a non-stream
arm makes it an `aggregator`, a stream-only annotation makes it a `composer`.

```text
count  -> int | Iterator[dict[str, int]]   subtype=aggregator  {aggregator, composer}
write  -> Stream                           subtype=composer    {composer}
```

Deleting the `int` arm to "match what callers see" silently reclassifies the
module in `get_module_metadata`. Leave it alone.

**Never assume the caller sees that union.** After the decorator, a `pipe`
*always* returns an iterator — even when the parser returned a scalar:

```text
next(pipe(stream))              -> {'count': 5}                 assigned
list(pipe(stream, emit=True))   -> [5]                          scalar, still in a stream
```

So use `Yields:` on `pipe`/`async_pipe` and describe **the element**, one bullet
per observable case. Reserve `Returns:` for `parser`/`async_parser`, whose union
is real and whose annotation owns it.

```python
    Yields:
        - ``{<group>: <count>}`` when ``count_key`` is set
        - ``{<assign>: <count>}`` when ``count_key`` is unset
        - ``count`` when ``emit`` is True and ``count_key`` is unset
```

Write the bullets **symbolically**, not as prose ("``<hash>``", not "the bare
hash"), and put the **default case first**.

#### Processors merge, operators nest

`assign` does two different things, and the notation has to show which:

```text
processor:  merged ``{Item, <assign>: <hash>}``   ->  {'content': 'x', 'hash': 123}
operator:   ``{<assign>: Item}``                  ->  {'uniq': {'x': 0}}
```

A processor writes its result *into* the item beside the original fields; an
operator nests the whole item under the field. Prose like "the original item
with `{<assign>: <hash>}` merged in" hides that — the two read as the same
shape. Use the literal forms above.

```python
    Yields:
        - merged ``{Item, <assign>: <hash>}`` when ``emit`` is False (default)
        - ``<hash>`` when ``emit`` is True
```

#### Assigning splits three ways, not two

`gen_assignments` branches on whether there is an item to merge into, and the
two branches have different *semantics* — not just different laziness:

```python
elif item and value_is_iterator:
    yield item | {assign: list(value)}       # ONE output, all values collected
elif value_is_iterator:
    yield from ({assign: v} for v in value)  # one output PER value, lazy
```

So a **multi-value** module needs three bullets, and the merge one must show the
list:

```python
    Yields:
        - ``<row>`` when ``emit`` is True (default)
        - ``{<assign>: <row>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<row>, ...]}`` when ``emit`` is False and
          item is given
```

A **single-value** module still needs all three — only the *merge* bullet
differs, because `one=True` makes `value` a scalar rather than an iterator, so
the list branch never runs:

```python
    Yields:
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - ``<value>`` when ``emit`` is True
```

**`operators` are the exception — they take two bullets, not three.**
`operator.process` always passes an empty `DotDict()` to `gen_assignments`, so
the merge branch is unreachable and there is no "item given" case:

```python
result = gen_assignments(DotDict(), assignment, assign=assign, one=one)
```

That is also why operators *nest* (``{<assign>: Item}``) rather than merge.
Processors pass the real `_input`, which may be empty or populated — hence
their third bullet.

Check which one applies by running it with and without an item — `csv` gives 645
outputs bare and *one* output (holding a 645-item list) when merged, while
`input` gives a scalar both ways.

The `list(value)` is required, not a missed optimization: collapsing N values
into one field means knowing them all before emitting. The corollary is that an
**unbounded** source with `emit=False` and an input item never returns, which is
worth a `Notes:` on any module that can produce an endless stream.

Every stated default and every bullet must be verified by running the module, not
inferred from the signature — `assign` defaults to the *module name*, and `emit`'s
default is derived from the parser's return annotation, so neither is visible at
the call site.

## Audience tiers (STABLE / EXTENSION / PRIVATE)

Determine a symbol's documentation tier in this order:

1. Exported from `riko` → **STABLE**
2. Exported from `riko.ext` → **EXTENSION**
3. Otherwise → **PRIVATE** unless a documented sub-API says otherwise

An underscore is a strong private signal, but `__all__` and the API-surface
contract are authoritative.

- **STABLE** — explain user-visible behavior and normal workflows; prefer
  executable examples; hide implementation machinery.
- **EXTENSION** — explain the contract an extension author must satisfy
  (lifecycle, invariants, protocols, callbacks, configuration, runtime
  interactions); include an example when it clarifies how to implement.
- **PRIVATE** — document non-obvious implementation knowledge: why the helper
  exists, invariants, assumptions, ownership, ordering, mutation, consumption,
  concurrency, or coupling.

Within a private module, split the rule by name:

- A **non-underscore function or class** — the module's own internal API, e.g.
  `gen_return_inferences` — carries **all** the sections its signature implies
  (`Args:`, `Returns:`/`Yields:`, `Raises:`) **plus an `Examples:` doctest**,
  **always**, even when it looks obvious, exactly like a STABLE or EXTENSION
  object. A public class demonstrates construction plus its primary behavior in a
  class-level `Examples:`. The summary and any prose lead with the **why,
  invariant, assumption, or trap**; the sections stack on top, never in place of it.
- An **underscore-prefixed helper may omit the sections — or the docstring
  entirely — when it is obvious**: `_matches_abc(candidate, abc) -> bool` needs
  none, and `"""Get the field."""` is worse than nothing. But the moment a `_`
  helper documents a why/invariant/trap, complete the sections its signature
  implies rather than stopping at prose.

The `Examples:` doctest is **required for the non-underscore case** and stays
**optional for underscore helpers** (reserved for where a compact executable
example clarifies non-obvious behavior). Either way it is real, meaningful
executable doctest demonstrating the function's own behavior — never illustrative
pseudocode padded in to satisfy the rule.

## House formatting (ruff-enforced)

This repo's ruff config enforces a specific physical layout for **multi-line**
docstrings:

- The opening `"""` sits on its own line; the summary starts on the **second**
  line (pydocstyle **D213**; **D212** first-line style is disabled).
- A **blank line precedes the closing `"""`** after the last section
  (pydocstyle **D413**).
- A **single-line** docstring stays on one line: `"""Return the field."""`.
- Run `ruff check --fix` after editing docstrings; it normalizes both rules.
- **Wrap docstring prose at 88 columns**, the same width as code.

That last one is *not* enforced automatically, and it is the easiest rule to
break: `E501` is in ruff's ignore list (`pyproject.toml`), and `ruff format`
does not reflow docstring prose — it only touches code. The 88 comes from
`[tool.pylint.format] max-line-length`. So a long `Args:` line passes
`ruff check`, passes `ruff format --check`, and still violates house style.

Check it explicitly after editing docstrings:

```bash
awk 'length($0)>88 {print FILENAME":"FNR" ("length($0)")"}' $(find riko -name '*.py')
```

Sync and async copies of the same paragraph must also wrap at the **same**
points. Where the async version carries an extra sentence the fill legitimately
differs; where the text is identical, the wrap must be too.

```python
def pipe(items):
    """
    Counts items in a stream.

    Args:
        items: Input stream.

    Yields:
        Count results in stream form.

    """
```

## Module docstrings

These rules apply to Python modules across the entire `riko/` package, not only
`riko/modules/`.

Every module keeps a user-facing description. Every public module, and every
private module that defines a re-exported public API, also keeps at least one
basic usage example. Pure private implementation/type modules with no public
entry point follow the private-module exception below.

A module example is an **entry point**, not a comprehensive test suite — prefer
*one* representative public workflow, exercising the module's public surface
(e.g. `pipe`) rather than an internal helper (`parser`). This is a soft limit,
not a hard cap: retain additional examples when they demonstrate a materially
distinct first-class mode or complete the module's primary workflow in a way
one example cannot. Do not add variants merely to enumerate configuration
options. Add `Attributes:` for module-level constants.

```python
"""
Counts items in a stream.

Examples:
    Basic usage::

        >>> from riko.modules.count import pipe
        >>>
        >>> items = [{"x": x} for x in range(5)]
        >>> next(pipe(items))
        5

Attributes:
    DEFAULTS: Default operator configuration.
    OPTS: Operator decoration options.

"""
```

Reducing a public module docstring to a bare one-liner is a regression: prose
may shrink, but the useful entry-point example stays. Removing a second example
solely to satisfy the one-example preference is also a regression when that
example demonstrates a distinct first-class mode or completes the primary
workflow. Package `__init__.py` files are exempt from the module-example
requirement, not from the package-docstring contract below.

**Keep it user-facing.** A module docstring answers *what this is for* and *how
to use it*. It is the first thing a reader sees, so it must not spend its space
on mechanism. Leave out the data structures, sentinels, tokens, control flow,
and cross-module call paths — those belong on the function or method that
implements them, where a reader arrives already knowing what they are looking
at. Design rationale, planned changes, and gameplan/phase references belong in
`_docs/`, never in a docstring.

```text
Bad:   receivers are primed generators whose items land in a ``deque``;
       completion uses a DONE sentinel plus per-receiver identity tokens.
Good:  Delivers items to named receivers within a single synchronous run.
```

The test: if a sentence would stop being true after a refactor that changed no
behavior, it is mechanism and does not belong. Applies to *any* module,
underscore-prefixed or not — a private module's reader is still arriving cold,
and a stale mechanism summary misleads faster than no summary at all.

### No internal jargon in shipped text

Internal planning vocabulary — phase codes (`R4B`, `R5C`, `P10`), gameplan
section refs (`§E3.6`), `_docs/` paths, and internal ticket ids — must never
appear in text a user or contributor reads outside the design docs (`manage lint
--terms` flags phase codes). That covers
**every shipped or user-facing surface**:

- docstrings and doctests;
- code comments;
- test names and `xfail`/`skip`/`raises` reason strings (say *what* is pending in
  plain English — "the pending callable-pipe support", not "R4B");
- `docs/*.rst` (changelog, migration guide, cookbook, FAQ);
- exception, log, and warning messages emitted at runtime.

Describe the behavior or the pending capability in plain English instead. Phase
codes and gameplan cross-refs stay in `_docs/` (gameplans, `IMPLEMENTED.md`) and
`CLAUDE.md`, which are the internal design record. A strict-xfail tripwire, for
example, names the *capability* it waits on, not the phase that owns it.

The same rule fixes the names of the workflow forms. Shipped text calls each by its
type name:

- `Workflow` — the in-memory graph object;
- `RawWorkflow` — the shorthand mapping a person writes (`WorkflowLike` when a
  `Workflow` is accepted too);
- `WorkflowDocument` — a serialized `Workflow`, introduced once as a **workflow
  document**;
- `PipeDef` — the older `src`/`tgt` form, introduced once as a **pipe definition**;
- `PipeDag` — the bare-bones DAG mapping;
- `WorkflowModule` — Python source defining `pipe` and/or `async_pipe` functions that
  take an item, a stream, or nothing, plus a `context`, introduced once as a
  **workflow module**. The shape defines it, not the author: `compile_workflow`
  output, a hand-written module, and a hand-edited one are all `WorkflowModule`s. The
  name covers the source only, never a loaded module.

Two more terms name the roles these forms play at run time:

- **stored workflow** — a workflow looked up by its `pipe_<id>` name; defined once
  per file like the forms above. A **workflow store** (a registered package, directory,
  or mapping) holds it as an importable module, a `WorkflowDocument` file, or an
  in-memory module, so never define it as a `WorkflowModule` or `WorkflowDocument`.
  The id is the store's lookup key, not part of the workflow. Sentences about the
  lookup itself say "`pipe_<id>` name";
- **resolved workflow** (`ResolvedWorkflow`) — the `types.ModuleType` exposing `pipe`/`async_pipe` that
  resolving a stored workflow yields, whether imported as is or built from a
  `WorkflowDocument`. Never call it a `WorkflowModule` or a bare "workflow
  module". Write the stdlib type as `types.ModuleType` in prose, since
  `riko.ext.ModuleType` is the processor/operator/splitter literal.

The other Python form `run-pipe` executes — a file defining `pipe(test=False)` — is a
**pipe script**. Its `pipe` signature, not its author, sets it apart from a
`WorkflowModule`, and a workflow store cannot load it. It has no type: `run-pipe` loads
any `.py` path and checks only for the `@workflow` stamp on `pipe` (an undecorated file
of either shape runs as a pipe script), so a type would claim what nothing checks.
Never call either Python form a "pipe file" or "pipe module": "pipe module" already
means a `PipeDef` module entry (`PipeModule`).

How a concept gets its own type depends on who produces the value:

- **riko produces it, callers only receive it** → a `NewType`, wrapped where riko
  produces it (`WorkflowModule`, `ResolvedWorkflow`). Type checkers show a `NewType` by
  its name; they expand a `type` alias to its target in hovers and signatures.
- **callers supply it** → a `type` alias or no type (`WorkflowDocument`, a stored
  workflow's `pipe_<id>` name). A `NewType` would make every caller wrap literals and
  parsed values. Inputs stay wide even when the output is a `NewType` (`MappingStore`
  takes plain `types.ModuleType`s and wraps them).
- **the code can't tell which kind it holds** → no type, and say what it may be in the
  docstring (the modules `run-pipe` loads).

Introduce "workflow document", "pipe definition", "workflow module", and "stored workflow" once per file (once per section
in a long guide such as the cookbook), then use the type names. Docstrings are the
exception: readers land on a class or function, not the top of its file, so each
docstring glosses the terms it relies on in place — ``WorkflowDocument`` (a serialized
``Workflow``), a resolved workflow (a module exposing ``pipe``/``async_pipe``) — rather
than leaning on the module docstring. The older JSON has no
document type of its own, so it is a "serialized `PipeDef`" (likewise "serialized
`PipeDag`"). Headings, CLI `--help` text, and runtime/log messages are read on their
own: they use the plain prose terms without backticks. "v1"/"v2" appear only when
quoting a surface that uses them (`--format {dag,v1,v2}`, `migrate_v1_to_v2`); never
write "canonical document/workflow", "v1/v2 document", "authoring form/mapping",
"released pipe definition", or "pipeline/workflow definition" for one of these forms.
A changelog entry
also describes a change against the **last release tag**: a name that only existed
between releases is never "renamed" or "removed" in `docs/CHANGES.rst`.

### Preserving examples during cleanup

Before shortening a module docstring, inventory its existing examples and classify
each one:

- **same workflow, different option/value** — usually keep one representative
  example and remove the rest;
- **distinct first-class mode** — keep it (for example, `loop` emit versus
  assign/fold behavior);
- **workflow completion** — keep the steps needed to show the abstraction's
  primary use end to end (for example, register then resolve);
- **different public surface** — keep it when the module genuinely exposes both
  surfaces and neither is adequately demonstrated elsewhere;
- **imported/library concept or implementation mechanism** — remove it from the
  module docstring; point to or test the owning concept instead.

Do not optimize for example count. Optimize for the smallest set that teaches the
module's real public shape.

When removing executable examples:

1. Check function/class doctests and pytest coverage before adding anything.
2. If the removed behavior has no executable owner, move it to the appropriate
   test before deleting it from the docstring.
3. Do not add a pytest test when an existing function/class doctest already owns
   the same behavior.
4. If an example is later restored as an executable doctest, remove any pytest
   test that was added solely to preserve that identical happy path.
5. Keep edge/error/non-deterministic/integration behavior in pytest even when a
   related happy path appears in a doctest. When a doctest grows past basic usage,
   move its extra cases into the subject's pytest table.
6. An edge or error case shown in both a doctest and pytest leaves the doctest
   when the doctest already shows several other basic use cases. When it does
   not, prefer rewriting the doctest to show basic usage and keep the edge case
   in pytest. Basic usage lives in its most appropriate doctest: when it is shown
   elsewhere, move it into this doctest only if this is the better home (and let
   the move trickle down to the doctest it leaves); never duplicate it just to
   give a doctest something to run. Only when no basic usage belongs in this
   doctest does it keep the edge case and the pytest copy go.

Removing prose that merely taught an external/library concept does not require a
replacement test. Removing a concrete user-visible Riko behavior does.

Generated module docstrings follow the same rules, but the canonical edit belongs
in the generator. Never patch only the generated file.

### Private modules

An underscore-prefixed module gets a module-level example **only when it has a
public API** — a name it defines that is re-exported from `riko`, `riko.bado`,
`riko.ext` (including `riko.ext.codegen`), `riko.modules`, or `riko.types`. When it
does, the example imports through that public path, never the private one:

| Module | Public surface | Module example |
|---|---|---|
| `riko/modules/_decorators.py` | `processor`, `operator`, `splitter` | yes — `from riko.ext import processor` |
| `riko/modules/_inference.py` | none | no |
| `riko/cli/_coverage.py` | none | no |

Otherwise the module keeps its description (and `Attributes:` for module-level
constants) and stops there. A module-level example is the reader's entry point
into a supported surface; a private module with no public surface has no entry
point to advertise, and demonstrating one would contradict the "public examples
exercise the public object" rule under Doctest rules. This bounds only the
*module* docstring — a private function may still carry a local doctest where a
compact executable example clarifies non-obvious behavior. `manage lint --docstrings`
enforces both this rule and the public-path rule for example imports.

## General docstring rules

- Triple-double-quoted; the summary is a concise descriptive line
  (placed per the house formatting above).
- Summaries read as *this object does X* — use **third-person present**
  (`Counts`, `Formats`, `Configures`), not the imperative (`Count`, `Format`,
  `Configure`). D401 is disabled precisely to allow this. A noun-phrase summary
  is fine for a class/type (`An immutable environment a module runs in.`).
- A summary **never begins with `Returns`/`Yields`** — describing the output is
  the `Returns:`/`Yields:` section's job, and a `Returns`-led summary only
  restates it (and usually the function name too). Lead with the *action*:
  `default_user_agent` → not `"""Returns the default user agent string."""`
  (echoes the name, duplicates `Returns:`) but
  `"""Formats the default user agent as name/version."""`.
- Blank line after the summary only when more detail follows.
- Do not repeat the signature or annotated types; document semantics, not syntax.
- Sections, only when needed, and always in this order: `Args:` → `Kwargs:` →
  `Returns:`/`Yields:` → `Raises:` → `Examples:` → `Notes:`. `Examples:` is
  never first among the sections — a docstring that jumps from the summary
  straight to `Examples:`, skipping `Args:`/`Returns:`, is the single most
  common miss. Never leave an empty section.
- `Args:` documents the parameters a caller may pass positionally; `Kwargs:`
  documents the keyword-only ones (after `*` or `*args`) and the entries of a
  `**kwargs` bag. The signature already forces those names to be keywords, so the
  docs mirror that split. A keyword-only parameter with its own annotation carries
  no type label. Every entry of a `**kwargs` bag does, because the signature gives
  it no explicit hint: that includes an `Unpack[SomeTypedDict]` bag, so readers
  never have to look up the `TypedDict` to learn an entry's type (see the
  exception above). When `Kwargs:` names a bag's entries, do not also list the bag
  under `Args:`.
- Give every non-underscore function the sections its signature implies: `Args:`
  for its parameters, `Returns:`/`Yields:` for its output. Model it on the file's
  *fullest* docstring, not its thinnest — in `riko/io/_sync.py` that is
  `ext_from_content_type`/`seekable`, not a bare summary. This holds across all
  tiers: a private module's public-named function is documented as completely as a
  STABLE one. An underscore-prefixed helper may still stay bare when obvious (see
  the PRIVATE-tier rule above), but once documented it never stops at prose when
  its signature implies `Args:`/`Returns:`/`Yields:`.
- Do not document `self` or `cls`.
- Do not restate defaults obvious from the signature unless the default has
  semantic importance.
- Use `Yields:` when the caller consumes the result as a stream; use `Returns:`
  for a single value. Describe what the caller observes, not how the function is
  implemented — a `pipe` that is `return parser(...)` still uses `Yields:`,
  because every `pipe` hands back an iterator (see "The two returns of a pipe callable").
- The summary names what the helper is *for*; the output description belongs in
  `Returns:`/`Yields:`, never in the summary. So do not lead with `Returns`/
  `Yields` (see the rule above) and do not narrate the body:
  `"""Yields from stream, then closes f."""` both restates the section and
  describes the loop. Write `"""Passes stream through, closing f when iteration
  ends."""` plus a `Yields:` section naming the element.
- The detail paragraph after the summary states *what the caller gets*, not *how
  it is produced*. Do not name the internal collaborators a function delegates to
  or narrate its sequence of transformation steps — that is the same mechanism the
  module rule excludes (see "Keep it user-facing"), and it applies to every
  docstring, function or module. Two or three plain sentences is the target; a
  paragraph that reads like a design doc is a regression even when accurate. The
  refactor test decides: if a sentence would change wording after a
  behavior-preserving refactor, it is mechanism and belongs in `_docs/`.
- Classes document the abstraction + constructor semantics; do not duplicate the
  class docstring in `__init__`. Give `__init__` its own docstring only for
  initialization behavior not reasonably documented on the class.
- Properties document the exposed value as a noun, not a getter
  (`"""Whether the input stream has been fully consumed."""`).
- Exception classes stay short — usually a single line.
- Declarative type objects (`TypedDict`, `Protocol`, enum, pure-data `dataclass`)
  document the concept in prose/`Attributes:`; no invented doctests for objects with
  no runtime behavior worth demonstrating. A public class **with** runtime behavior
  (methods, construction validation, a resolved view) carries a class-level
  `Examples:` like any other public object.
- Most straightforward dunders need no docstring when the class already defines
  the behavior; cross-reference (`equivalent to :meth:\`run\``) instead of
  duplicating.

### String values, names, and labels

A double-backtick literal is Python source: write it exactly as a reader would type
it. This applies to docstrings and `docs/*.rst` alike.

- A **string value** — anything passed, returned, yielded, or compared — keeps its
  quotes inside the literal: ``"thread"``, ``""``, ``"3 days"``.
- A **name** — field, conf key, parameter, attribute, module, identifier — stays
  bare: ``content``, ``ftype``. The field ``content`` and the value ``"content"``
  are different things; the quotes say which is meant.
- A **label** — a value's word used as ordinary English for a mode — takes no
  backticks: "the thread executor", "the inline executor".
- The pipe-convention `(default: …)` and the FAQ option table's default column are
  plain text, written as the Python value: `(default: "content")`, `(default: False)`.
- Double quotes, per the doctest rule below; single-quoted ``'x'`` appears only in
  expected output Python prints that way.
- A **callable named in prose** — function, method, or module verb — has no empty
  call parentheses: ``.first``, ``close``, ``aclose``, ``pipe.filter``. Keep ``()``
  only where dropping them would change or blur the meaning, e.g. a call being
  compared with another call (``SyncPipe("fetch")`` vs ``pipe.filter()``), or a call
  with arguments (``.pipe(name)``).

The test: pasted into Python, does the literal mean the right thing? ``thread`` would
be a variable, so a value needs ``"thread"``; ``"content"`` would be a string, so a
field name needs ``content``.

`manage lint --literals` flags the three mechanical slips: a backticked `(default: …)`
(an `ALL_CAPS` constant name is allowed), a single-quoted ``'x'``, and an unquoted
`(default: word)` whose parameter defaults to the string ``"word"``. Value vs. name
vs. label is a judgment call no lint makes.

```rst
Value:  ``executor`` accepts ``"thread"``.
Name:   Splits ``content`` on the delimiter.
Label:  The thread executor uses a pool.
```

## Doctest rules

Every `>>>` block anywhere — Python source, `README.rst`, or `docs/*.rst` — is
executable test code (`--doctest-modules` + `--doctest-glob=*.rst`). Never use
`>>>` for illustrative pseudocode; if an example must not execute, use a plain
code block without interpreter prompts.

- Treat doctests as executable user documentation first, tests second.
- Show actual returned values, not boolean assertions
  (`>>> next(pipe(items))["count"]` → `5`, not `... == {"count": 5} → True`).
- Follow Arrange → Act → Observe; keep each example focused on one behavior.
- Every code block runs on its own: it imports and defines everything it uses,
  even when an earlier block in the same file or section already did, because
  readers land on a block directly. Repeating that setup across blocks is
  expected, never duplication to remove. Within one block, never rebind a name:
  give each step its own name (`page`, `feed`, `merged`).
- Name inputs by role: `items`, `result`, `stream`, `conf`, `pipe`.
- Prefer `list(result)` when demonstrating the complete sequence; `next(result)`
  when streaming/laziness is the point.
- Deterministic, local inputs only; never require live network, current time,
  unstable reprs, memory addresses, unordered output, or environment paths.
- ELLIPSIS is globally enabled; use it only for a genuinely unstable portion.
- Separate the import block from the rest of the example with a single empty
  `>>>` prompt. A bare `>>>` is valid doctest source (it expects no output), and
  it keeps the setup visually distinct from the workflow being demonstrated:

  ```
  >>> from riko.modules.count import pipe
  >>>
  >>> next(pipe([{"x": x} for x in range(5)]))
  5
  ```

  Also put one before each `def` / `async def`, which gives a nested block
  breathing room and separates it from the statements around it:

  ```
  >>> from riko import run
  >>>
  >>> async def main():
  ...     result = async_pipe(items)
  ...     print(await anext(result))
  >>>
  >>> run(main)
  ```

  Those two positions only — no other empty prompts for visual spacing. A true
  blank line still terminates the example, so it can never substitute for `>>>`.
- Narrate a case inside the example as a `>>> #` comment, not as prose between
  examples, and write names plainly (no RST markup) since the comment renders as
  code:

  ```
  >>> # A falsy value passes unless strict is set
  >>> require_arg([], "others", "send")
  []
  ```

  A labelled block (`Basic usage::`) still introduces a separate example group.
- Prefer double-quoted strings in example **input**; expected dict/`repr` output
  keeps whatever Python actually prints (usually single quotes).
- Public examples exercise the public object — do not reach through the API into
  private helpers.
- Private-object doctests are rare; use one only when a compact executable
  example significantly clarifies non-obvious behavior.
- **Doctests and unit tests share coverage, they do not duplicate it.** When a
  doctest demonstrates a behavior an existing unit test also asserts, extract the
  example *from* that test and delete the now-redundant test — the doctest is the
  single source. Reserve unit tests for what a doctest should not carry: exception
  and edge paths, unstable-`repr`/non-deterministic cases, and multi-step
  integration. A doctest shows basic usage; once it grows past that, its extra
  cases move into pytest. An edge or error case in both places leaves the doctest
  when the doctest already shows several other basic use cases. When it does not,
  prefer rewriting the doctest to show basic usage and keeping the edge case in
  pytest. Basic usage lives in its most appropriate doctest, so it may move into
  this doctest from elsewhere when this is the better home, with the move
  trickling down to the doctest it leaves; never duplicate it just to give a
  doctest something to run. Only when no basic usage belongs in this doctest does
  it keep the edge case and the pytest copy go. One row of a parametrized table
  counts as a test here. Before adding a doctest, grep the suite for an
  equivalent assertion; before deleting a test, confirm the doctest actually runs
  it (`--doctest-modules`).

## Python syntax baseline

Use idiomatic Python 3.12+:

- PEP 604 unions: `X | Y`
- built-in generics: `list[str]`
- PEP 695 type parameters where appropriate
- modern asyncio / AnyIO patterns

**There is no Twisted anywhere.** The optional async backend is AnyIO. Document
the async contract, not the machinery. When async support is unavailable,
`conftest.py` skips Async/Bado doctest items whole and, everywhere else (including
`.rst` files), skips just the examples that call `run(...)`. So do not add `issync`
fallback branches merely to make an async doctest pass in a sync-only environment.
The canonical async doctest form is:

```python
Examples:
    >>> from riko import run
    >>>
    >>> async def main():
    ...     items = ({"x": x} for x in range(5))
    ...     result = async_pipe(items)
    ...     print(await anext(result))
    >>>
    >>> run(main)
    {'count': 5}
```

Do not reintroduce `FakeReactor` / Deferred scaffolding.

## `__init__.py` policy

Treat `__init__.py` as an API boundary, not an implementation dumping ground.
Keep it thin, cheap to import, and explicit about exports. `__init__.py` runs at
import time.

**STABLE and EXTENSION namespaces:**

- Keep the initializer thin; re-export only intentionally supported names.
- Declare those names explicitly in `__all__`. `__all__` is an API contract, not
  a list of convenient imports — never put a private implementation object in
  `__all__` merely because a sibling needs convenient access.
- Keep the canonical implementation in its defining submodule; import internals
  from there (`from riko.modules._prepare import PreparedModule`), not through a
  public-looking namespace.
- Document the namespace's purpose, audience, stability, and package-wide
  semantics — not how every exported object works. A vague one-line summary is
  a regression when it drops one of those boundary facts.
- Keep package doctests minimal; tutorials belong in `README.rst`/`docs`.
  Package examples are optional, but keep one when the package itself exposes a
  distinct package-level workflow that is not better owned by a submodule.

**PRIVATE namespaces:**

- Do not construct an accidental facade; import only what package operation needs.
- Do not re-export internals solely for shorter internal imports.
- A one-line package docstring suffices unless architecture/invariants need
  explaining. `__all__ = []` may be used to declare "no public API".

**Import-time work:** avoid new filesystem/network access, expensive discovery,
registration scans, or substantial object construction in `__init__.py` unless
package initialization itself requires it (e.g. `riko.bado` backend selection is
a justified exception).

When deciding whether to re-export a symbol, ask: *do we intend users or
extension authors to rely on this exact import path across releases?* If not,
import it from its defining module and keep it out of `__all__`.

**Package-docstring regression check:** when editing an `__init__.py`, compare the
old and new docstrings separately from the import diff. A STABLE/EXTENSION package
must still tell a reader what namespace they imported, who should use it, and what
stability/package-wide contract it carries. A PRIVATE package may stay concise,
but do not move architecture/mechanism into the package docstring merely to make
it longer.

## Degrade or raise

Two different failures get two different handlings, and the `Raises:` /
`Notes:` sections must say which applies.

**Degrade for runtime conditions.** The world failed you: a url that will not
fetch, a rate absent from a response, a malformed rule among several. Log a
`logger.warning` and carry on with the most meaningful remaining behavior, then
record it under `Notes:`. This is safe only when the data contract survives —
`write` can skip its write because items pass through byte-identical either way,
and `union` can drop a missing `others` because union-with-nothing is the
source.

**Raise for a missing required argument.** That is a call-site programming
error, not a runtime condition, and it is the one case where degrading is worse
than stopping: `aggregate`/`udf` without `func` would emit *untransformed items
that look correct*, so the mistake surfaces far from its cause as silent wrong
data. Use `require_arg` (`riko/base/_require_guards.py`), which names both the
module and the argument, and document it under `Raises:`. The argument is an
explicit keyword-only parser parameter typed `T | None = None` — optional to
Python so Riko can raise its own error, required to Riko.

```text
Bad:   KeyError: 'func'
Good:  TypeError: the 'aggregate' pipe requires the 'func' keyword argument
```

The dividing line is whether an identity behavior exists that leaves the data
honest. A *modifier* has one; the *operand* the module exists to apply does not.
The four operand cases are `aggregate`/`udf` (`func`), `join` (`other`), and
`send` (`others`).

## Reserved terms

Some words already name a specific riko concept. Using them loosely sends the
reader to the wrong place.

| Term | Means | Say this instead |
|---|---|---|
| **coroutine** | `riko.runtime._pubsub.coroutine` — a *generator* coroutine primed for `.send()`, used by the `send`/`receive` pub/sub modules. **Not** async. | "async function" for anything `async def` |
| **stream** | an iterator of items | don't use it for a single item |
| **item** | one dict-like mapping of field names to values — the unit a stream carries | don't use it for a stream; an item's entries are *item fields*, not "item attributes" (an attribute is a Python attribute) |
| **record** | a row in an external representation — inside a fetched document (`fetchdata`'s `path`), a keyed write target, a serialized file — or a fixed-field structure (an attrs record, `LogRecord`) | "item" for anything flowing between nodes, including what a write receives or serializes |
| **feed** | an RSS/Atom feed (`fetch`, `fetchsitefeed`, `feedautodiscovery`); in backticks, ``Feed`` is the `Items \| AsyncItems` type (sync or async items) | "stream" for any other sequence of items; "async iterable" for a generic one |
| **source** | a module that creates items (the `Sources` enum, the `"source"` category/subtype: `fetch`, `csv`, `itembuilder`); an edge's `source`/`target` endpoint keeps its graph meaning when qualified ("source port") | "input stream"/"input item" for what a module receives, so never "async source" (say "async input stream", or "async iterable" for a generic one); "seed" for the items handed to a `Pipeline` |
| **target** | a `Target` endpoint identified by its backend (`FileTarget`, `SupportsRead`/`SupportsWrite`, the target registry); an edge's `target` endpoint keeps its graph meaning when qualified ("target port", "target node") | "format" for a `Formats` value or what `export` serializes to ("export format", never "export target"); "destination" only for where a write lands (`dest`), never "destination type" for a cast type |
| **provider** | the namespace a module name carries: its first dotted segment (`example.lookup` → `"example"`), or `"riko"` for an unqualified built-in; `ModuleMetadata.provider`, `list_modules(provider=)`, and one generated discovery class per provider | "category" for a module's data-flow role (`"source"`/`"transform"`/`"sink"`); "backend" for a `Target`'s kind (`Backends`), so an action target runs a "backend command", never a "provider command"; "extension package", never "provider package", for the installable distribution that ships a provider's modules |
| **cleanup** | what an execution does to release a resource when it is done with it: closing an owned value, calling a `cleanup=` callback, or exiting a lifecycle; "cleans up", "async cleanup", `requires_async_cleanup`/`has_async_cleanup`; a write session's resource release is its `close()`/`aclose()` | never "teardown", "tear down", "tears down", or "torn down"; "close" for the specific act on an owned value, stream, or write session; pytest's own teardown phase is reworded ("after the test ends") rather than exempted |
| **shutdown timeout** | the `shutdown_timeout` execution setting: how long an execution's cleanup may run before it is cut off | never "shutdown budget"; "node-thread budget" names `RIKO_NODE_THREADS` |
| **seed** | the items handed to a `Pipeline` run (`pipeline(items)`, `items \| pipeline`, `pipeline.open(items)`); "seeds a pipeline" | never for starting a pipeline from a module (`from_module` "starts from" one); "starting value" for a reduce accumulator |
| **module** | a named, reusable riko unit such as `fetch` or `hash` (`from_module`, `list_modules`, `Modules`); its processor/operator/splitter classification is its *module type*; as a sentence subject it is "the ``sort`` module", while lists, possessives, and a qualifying noun take the bare name ("``fetchdata``, ``fetchpage``, and ``csv``", "``union``'s ``others``", "a ``filter`` rule") | "Python module" or `types.ModuleType` for an importable Python module — a bare "module" is always a riko module; `ModuleStore` and the `ModuleType` literal are identifier exceptions |
| **node** | a module placed in a workflow with its conf and options (`ModuleNode`, ids like `sort-1`); a `Pipeline` is a chain of nodes | not "pipe", "step", or "configured pipe" |
| **pipe** | only a verb (`Pipeline.pipe(name)` "pipes the stream into" a module) or a callable's name: a module's `pipe`/`async_pipe` (a "pipe callable", the one noun for what a decorator returns) or a resolved workflow's `pipe` | never a noun for a module or a node ("the `fetch` module", not "the fetch pipe"); not "module wrapper" or "decorated pipe" for a pipe callable in user prose (`ModuleWrapper` keeps its type name); never for the `parser`; `pipe_<id>`, `PipeDef`, "pipe script", and `run-pipe` keep their names |
| **pipeline** | the variable bound to a `Pipeline` (`pipeline = Pipeline.from_module(...)`, `stream = iter(pipeline)`) | never `flow = Pipeline(...)` |
| **flow** | the variable bound to a bare `Workflow` graph: a parameter, local, module-level, or doctest binding (`flow = pipeline.workflow`, `compile_workflow(flow, ...)`, a workflow module's `flow`); instance fields (`pipeline.workflow`, `ExecutionPlan.workflow`), the `from_workflow` name, and the `workflow=` keywords that set those fields (constructors, `evolve`) keep theirs (`manage lint --bindings`); a `RawWorkflow` mapping is `raw` | don't use it for a `Pipeline`; never `workflow = Workflow(...)` (`workflow` is the decorator) |
| **`Workflow`** | the in-memory graph object (`Workflow.parse`, `migrate_v1_to_v2` return one) | not "canonical workflow", "spec", or "workflow document" |
| **`RawWorkflow`** | the shorthand mapping a person writes, before normalization | not "authoring mapping" |
| **`WorkflowDocument`** | a serialized `Workflow` (bytes); "workflow document" on first use | not "canonical document", "v2 document", or "pipeline JSON" |
| **`PipeDef`** | the older `src`/`tgt` mapping; "pipe definition" on first use; on disk, a "serialized `PipeDef`" | not "v1 document" or "older pipe definition" |
| **`PipeDag`** | the bare-bones DAG mapping; on disk, a "serialized `PipeDag`" | not "DAG document" |
| **`WorkflowModule`** | Python source defining `pipe`/`async_pipe` over an item, a stream, or nothing, plus a `context` — what `compile_workflow` returns, or the same shape written by hand; "workflow module" on first use; never a loaded module | not "generated module", "pipeline module", "compiled pipeline", or "pipe module" |
| **stored workflow** | a workflow looked up by its `pipe_<id>` name, found by `WorkflowResolver` in a workflow store; defined on first use | not "named workflow", "registered workflow", "named/composed pipeline", or "sub-pipeline" |
| **resolved workflow** | `ResolvedWorkflow`: the `types.ModuleType` a stored workflow resolves to, imported as is or built from a `WorkflowDocument` | not `WorkflowModule`, "workflow module", or "imported workflow" |
| **pipe script** | a hand-written Python file defining `pipe(test=False)` that `run-pipe` executes | not "pipe file" or "pipe module" |
| **resource binding** | a node's `resources=` mapping of local alias (the slot a module reads) to Context resource name; the verb *bind* means only this ("the Context names a node binds") | never for adding a definition to a `Context`: a Context *provides* a resource (`with_resource`); never for fixing a call's arguments (*prepare*/*apply*) or attaching callables (*attach*); a Python name binding (`flow = ...`, `manage lint --bindings`) keeps its language meaning |
| **prepare** | fix a module call's configuration and call options once for reuse over many items (a pipe callable's `prepare`, the `Preparer`/`PreparedCall` protocols, `prepare_call`, `Module.prepare`); the result is a *prepared* call or pipe | never "bind" (*bind* is reserved for resource binding) or "bound keywords" (say "keyword arguments"); "apply" for keyword arguments fixed on a plain callable |
| **registry** | a `Registry[T]` only: the module registry (`ModuleRegistry`, `module_registry`) or the target registry (`TargetRegistry`); entries resolve runtime → entry point → built-in | not for `WorkflowResolver`, the dispatcher, a workflow store, export formats, or the pub/sub receivers |
| **register** | add an entry to a registry's runtime tier (`register_module`, `register_target`) or add a workflow store (`register_workflow_store`) | "declare an entry point" for the entry-point tier; "available"/"resolvable" for any module, built-ins included (built-ins are not registered); never "registered workflow" |
| **resolver** | always qualified: the workflow resolver (`WorkflowResolver`) or the `Resolver` protocol | "dispatcher" for `ResolverDispatcher` |
| **dispatcher** | `ResolverDispatcher` (`dispatcher`): routes a module name to the module registry and a `pipe_<id>` name to the workflow resolver | not "resolver" or "resolver façade" |
| **catalog** | the module catalog: what `list_modules()`/`describe_module()` report over built-in, entry-point, and runtime-registered modules (`catalog_names` is a registry's share of it) | "serialization formats"/"export formats" or the `Formats` enum for what `export`/`write` serialize to |
| **store** | a workflow store (`WorkflowStore`: a module store or a document store) that a `pipe_<id>` name is looked up in | always qualify a later kind ("state store", "checkpoint store"); never for a registry |
| **extension package** | an installable package that declares riko entry points (`riko-example-ext`) | not "plugin" or "entry-point plugin" |
| **execution mode** | only the `ExecutionMode` enum (`RUN`/`DESCRIBE_*`, `Context.mode`): whether a workflow runs or only describes itself | "sync or async" for how a pipeline is iterated (`for` vs `async for`, a module's `pipe` vs `async_pipe`): "uses one callable for both sync and async", not "both execution modes", "both sides", "each side", "the chosen side", "the missing side", "the other side", "the other mode", "host-mode", "cross-mode", or "engine". Split by reader: prose for pipeline users (module behavior, user docs, their changelog bullets) says "a sync run"/"an async run", since they only iterate; prose for extension authors (decorators, `ModuleDefinition`, registry, workflow modules) names `pipe`/`async_pipe`; "interface" appears only as the `Interface`/`interfaces`/`require_interfaces` identifiers, never "sync interface" or "async interface" in prose |
| **execution** | the private one-shot object that carries out one run (`SyncExecution`/`AsyncExecution`, `subject="execution"`), the execution layer, and its settings (`with_execution`, `ExecutionSettings`, "execution-wide") | not a public object: users hold an iterator, not an execution |
| **run** | one iteration of a `Pipeline` from start to cleanup: it owns that iteration's resources ("the run's resources", "cleans the run up", "varies between runs"); `PipelineStream` names the handle `pipeline(items)` returns and `PipelineRun` the context manager `pipeline.open(items)` returns | not "execution" in user-facing prose about the lifetime; never "scoped run" or "scopes a run" for `open()` (say it returns a context manager); `ExecutionMode.RUN` is the run-vs-describe choice, not a lifetime |
| **context** | the `Context` a module runs in: the run environment that supplies `mode`, `inputs`, the `test` flag, and the resources it provides (`with_context`, the `context=` parameter); an immutable definition, not part of the execution | not "execution context" or "pipeline context": a `pipe` parameter line reads `context (Context): the run environment`; say "context manager" in full for a `with` target |
| **input** | qualified in its riko senses (plain "the input" for a function's argument or a CLI file is ordinary English). *Input values* are the answers a run supplies (`Context.inputs`, the `inputs=` keyword argument) that an `input` module reads by its `input_key` instead of prompting; *input declarations* are a workflow's typed inputs (`Workflow.inputs`, full JSON Schemas; describe-inputs mode reports them); an *input port* is where an edge enters a node (`in`, positional `in:N`, named `in:<name>`), and every port delivers an *input stream* (the default one, or a "secondary input stream" through `in:N`/`in:<name>`); the `input` module keeps its name | never bare "inputs" in prose; not "value input" for a named port (it carries a stream); not "source" for a secondary input stream; not "input requirements" for input declarations |
| **output** | qualified in its riko senses (an output file, printed output, or serialized output is ordinary English). A node's *output stream* is what it yields after `count`/`assign`/`emit` shape its results, and it pairs with the input stream the next node receives (a stream on an edge is the upstream node's output stream until a port takes it, then that port's input stream; never an "upstream stream"); an *output port* is where an edge leaves a node (`out`, positional `out:N`, named `out:<name>`); a *workflow output* is a named endpoint a workflow exposes (`Workflow.outputs`), and the *default output* is the one a `Pipeline` yields; a `PipeDef`'s terminal marker is its ``output`` node | never bare "output(s)" in prose; not "output" for what a parser returns (that is a result); not "output module" (there is no such module) |
| **result** | what a module's parser returns: zero or more per input item for a processor, one reduced value for an aggregator; `assign` names the field a result is assigned to, `emit` yields it as is, `count` sets how many to keep. `WriteResult`, `FeedResult`, and `ActionResult` keep their names in backticks | never "results" for the items a pipeline yields ("items", "whether items keep source order", "Exporting a stream"); "the result of `Workflow.parse`" stays ordinary English |
| **terminal** | only a conf *terminal reference* (`{"terminal": "<name>", "type": …}`, the `Terminal` conf type): it takes the next item from the secondary input stream wired into `in:<name>`; its `type` is the *terminal type* (a shell terminal stays ordinary English) | "consumes the stream" for a call that ends a pipeline (`export()`), never "terminal call/verb"; "the `PipeDef` `output` node" for the old `_OUTPUT` marker; "secondary input stream" for a stream passed as a keyword argument, never "terminal sub-source" or "terminal input" |
| **key** | always qualified: a *conf key* ("no ``url`` key"), a *sort key* (`build_sort_key`), the *match keys* a keyed write needs (`write(keys=)`), or a lookup/registry key; the `*_key` conf names (`count_key`, `join_key`, `input_key`) keep their names but each *names a field*; a mapping key in a generic helper is ordinary English | "field" for anything naming item data; "group value" for what a grouping reports per group; "subkey" only for the `{"subkey": …}` reference |
| **sink** | a receiver of side-channel values: the *event sink* (`EventSink`, `event_sink=`) and, later, the error sink; until the `write` module retires, also the `Sinks` discovery category ("sink module", `category="sink"`) | never a call or verb that ends a pipeline (there is no `sink()`; a call that ends one "consumes the stream"); never "sink pipe"; "write" or "target" for where items end up |
| **dependencies** | the modules and stored workflows a workflow uses: the generated `DEPENDENCIES` list, `ExecutionMode.DESCRIBE_DEPENDENCIES`, `Context.describe_dependencies`; a package requirement is always qualified ("optional dependency", "dev dependencies") | "upstream"/"downstream" nodes for graph order between nodes (`GraphIndex.upstream`/`.downstream`, "upstream subgraph"), never "dependencies"/"dependents"; what a node receives is its *input stream*, never an "upstream stream" |
| **describe** | report information instead of running: `describe_module` returns a module's metadata; the *describe modes* (`ExecutionMode.DESCRIBE_INPUTS`/`DESCRIBE_DEPENDENCIES`/`DESCRIBE`) make a workflow module's `pipe` return its input declarations or dependencies | always "describe mode" for the mode, never a bare "describe" |
| **connection** | a live client connection to an external system (a database connection, an HTTP session) — the kind a resource provides | "edge" for a graph edge (`incoming`/`outgoing` hold edges); "concurrency limit" for a cap on in-flight calls (`RIKO_CONCURRENCY_LIMIT`) (`async_map`'s `limit`); "strongly connected component" and Riko Connect are unaffected |
| **parser** | the function a module author writes and decorates (`def parser(...)` under `@processor`/`@operator`; the parser protocols); what it returns is its *result* | always qualify a document library ("XML parser", "HTML5 parser", "feed parser": lxml, html5lib, feedparser); "document format" for what a file extension selects; "parsing" for the activity |
| **emit** | in module and user docs, only what the `emit` call option does: yield the result as is instead of assigning it; `EventSink.emit` ("emits an event") keeps the event sense | "yields" for producing items (or a specific summary verb, since summaries never start with "Yields"); not "emits" for a stream a module produces |
| **wire** | an entry of a `PipeDag` or `PipeDef` `wires` list (a `[source, target(, port)]` entry or a `{src, tgt}` `Wire` mapping); the verb "wire into a port" means connect | "edge" for a `Workflow`'s connections (`StreamEdge`, `edges`), never "wire" |
| **path** | always one of: a filesystem path (`dest`, `get_path`, "the destination path"); a URL path (`urlbuilder`'s `path`); or a *dotted path*, an `"a.b.c"` address of a nested value, qualified by what it walks ("a dotted path into the item", "into the fetched document") | not "dotted key", "dotted name", or "dot separated path" (Python import names stay "dotted module name"); "a sync/async run" or "under sync/async iteration", never "the async path" or "both paths" |
| **configuration** | a module's `conf`: what that module does, checked against its `<Name>Conf` contract; "module configuration" in a parameter line; `DEFAULTS` is its "default configuration" | not for call options, decoration options, settings, or a `Context` |
| **call options** | the per-node `options` (`CallOptions`: `field`, `assign`, `emit`, `count`) that shapes any module's input and output; a call option overrides the default a module's decoration options give for the same key | never bare "options", "call-time options", or "module options"; `conf`, `context`, and `embed` are keyword arguments, not call options |
| **decoration options** | what a module author fixes at decoration time (`OPTS`, `DecorationOptions`: `extract`, `listize`, `ftype`, `ptype`, `objectify`, `parse`, `pollable`, `skip_if`) plus the defaults it gives call options | not "wrapper options" or "decorator options"; not part of a pipeline author's surface |
| **keyword arguments** | everything a pipe callable accepts (`conf`, the call options, `context`, `embed`, `inputs`); a parser's catch-all parameter is called `**kwargs`, never a "keyword sink" | not "options" or "kwargs" in prose |
| **settings** | always qualified: "execution settings" (`ExecutionSettings`, `with_execution`) or "process settings" (`Settings`, the `RIKO_*` environment variables) | never for a module's configuration, call options, or a `Context` |
| **type** | never bare in prose. *Module type* is only processor/operator/splitter (`ModuleType`, `list_modules(type=)`, a pipe callable's `.type`); a workflow node's or edge's kind is its *node family*/*edge family* (`family`); the module a node runs is its *module name* (`name`; a `PipeDag` may still spell it `type`, a `PipeDef` always does); a conf value's `type` is its *cast type* or *terminal type*; `export`'s `type_` is the *export type* | not "module ``type``" for a module name, and never `type` for a node family |

The `coroutine` collision is the one that actually bites: `iscoroutinefunction`
sits right next to the code you are documenting, so "coroutine function" is the
reflexive phrase — and it points a reader at the `@coroutine` decorator, which
is the opposite of what `async def` means here. `send`/`receive` legitimately
say "generator based coroutines"; that qualifier is what keeps it unambiguous.

## Voice

Name the thing. Say what it does. Add one sentence only when omitting it would
hide an important behavior. Let annotations, examples, tests, and architecture
docs carry the rest. STABLE objects teach application developers; EXTENSION
objects teach extension authors; PRIVATE objects teach maintainers only when the
code cannot efficiently teach itself.
