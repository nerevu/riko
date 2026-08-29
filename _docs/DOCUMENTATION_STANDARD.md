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

### Exception: `pipe`/`async_pipe` keep their type labels

The rule above assumes annotations that describe the call. Every module's
`pipe`/`async_pipe` is declared `(*args: Any, **kwargs: object)` — annotations
that describe nothing. There the docstring is the *only* record of the contract,
so it carries the types as well as the names.

This applies **only** to the `pipe`/`async_pipe` entry points. `parser` /
`async_parser` have real annotations (`stream: Stream, objconf: WriteObjconf,
tuples: PipeTuples`), so they stay typeless.

`conf` also keeps its nesting: its keys are entries inside a dict argument, not
parameters in their own right. Flattening them is a factual error — it tells the
reader to call `pipe(stream, count_key="word")`, which is not the signature.

```python
    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration.

            count_key (str): Field to count by. Groups items in the stream by
                the given key and reports a count for each group.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the count is assigned to. Ignored when ``count_key``
            is set (the group keys are used instead) or ``emit`` is True
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
pipes). Only the outermost argument is interpreted that way, so a list-valued
*field* inside a record stays one value.

Explain it once — the FAQ's *"How does a processor map over items?"* — and have
the module keep a one-liner pointing there rather than repeating the rationale
in all ~30 processors.

Document only the **user-facing** call-time options: `conf`, `context`,
`assign`, `emit`, and `field` where the module actually uses it. Omit the
module-author options — `ftype`, `ptype`, `extract`, `listize`, `objectify`,
`pdictize`, `dictize` — which are set once in the module's `OPTS` at decoration
time and are not part of the pipeline author's surface. The full kwarg table
lives once in `docs/FAQ.rst`; don't restate it per module.

When converting a legacy `Kwargs:` block, preserve every name and the
indentation that shows what nests under `conf`. Cross-check against the
function's own doctests: if an example calls
`pipe(stream, conf={"count_key": "word"})`, then `count_key` belongs under
`conf`.

### The two returns of a pipe

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

So a **multi-value** pipe needs three bullets, and the merge one must show the
list:

```python
    Yields:
        - ``<row>`` when ``emit`` is True (default)
        - ``{<assign>: <row>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<row>, ...]}`` when ``emit`` is False and
          item is given
```

A **single-value** pipe still needs all three — only the *merge* bullet
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
worth a `Notes:` on any pipe that can produce an endless stream.

Every stated default and every bullet must be verified by running the pipe, not
inferred from the signature — `assign` defaults to the *pipe name*, and `emit`'s
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
- **PRIVATE** — document only non-obvious implementation knowledge: why the
  helper exists, invariants, assumptions, ownership, ordering, mutation,
  consumption, concurrency, or coupling. An obvious helper needs no docstring;
  `"""Get the field."""` is worse than none.

Do not add `Args`/`Returns`/`Examples` mechanically to private helpers. A private
docstring earns its place by documenting a **why, invariant, assumption, or trap**.

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
        items: Source stream.

    Yields:
        Count results in stream form.

    """
```

## Module docstrings

Every module keeps a description plus a basic usage example. The example is an
**entry point**, not a comprehensive test suite — prefer *one* representative
public workflow, exercising the module's public surface (e.g. `pipe`) rather
than an internal helper (`parser`). Add `Attributes:` for module-level
constants.

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
    OPTS: Operator wrapper options.

"""
```

Reducing a module docstring to a bare one-liner is a regression: the description
may shrink, but the `Examples:` block stays. Package `__init__.py` files are the
exception — see the `__init__.py` policy below.

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

### Private modules

An underscore-prefixed module gets a module-level example **only when it has a
public API** — a name it defines that is re-exported from `riko`, `riko.bado`,
`riko.ext`, or `riko.modules`. When it does, the example imports through that
public path, never the private one:

| Module | Public surface | Module example |
|---|---|---|
| `riko/modules/_decorators.py` | `processor`, `operator`, `splitter` | yes — `from riko.modules import processor` |
| `riko/modules/_inference.py` | none | no |
| `riko/_io.py` | none | no |

Otherwise the module keeps its description (and `Attributes:` for module-level
constants) and stops there. A module-level example is the reader's entry point
into a supported surface; a private module with no public surface has no entry
point to advertise, and demonstrating one would contradict the "public examples
exercise the public object" rule under Doctest rules. This bounds only the
*module* docstring — a private function may still carry a local doctest where a
compact executable example clarifies non-obvious behavior.

## General docstring rules

- Triple-double-quoted; the summary is a concise descriptive line
  (placed per the house formatting above).
- Summaries read as *this object does X* — use **third-person present**
  (`Counts`, `Formats`, `Configures`), not the imperative (`Count`, `Format`,
  `Configure`). D401 is disabled precisely to allow this. A noun-phrase summary
  is fine for a class/type (`A pipeline execution context.`).
- A summary **never begins with `Returns`/`Yields`** — describing the output is
  the `Returns:`/`Yields:` section's job, and a `Returns`-led summary only
  restates it (and usually the function name too). Lead with the *action*:
  `default_user_agent` → not `"""Returns the default user agent string."""`
  (echoes the name, duplicates `Returns:`) but
  `"""Formats the default user agent as name/version."""`.
- Blank line after the summary only when more detail follows.
- Do not repeat the signature or annotated types; document semantics, not syntax.
- Sections, only when needed, and always in this order: `Args:` →
  `Returns:`/`Yields:` → `Raises:` → `Examples:` → `Notes:`. `Examples:` is
  never first among the sections — a docstring that jumps from the summary
  straight to `Examples:`, skipping `Args:`/`Returns:`, is the single most
  common miss. Never leave an empty section.
- Once a function earns a multi-section docstring, give it the sections its
  signature implies: `Args:` for its parameters, `Returns:`/`Yields:` for its
  output. Model it on the file's *fullest* docstring, not its thinnest — in
  `riko/_io.py` that is `ext_from_content_type`/`seekable`, not a bare summary.
  (This does not override the PRIVATE-tier rule that an *obvious* helper needs
  no docstring at all; it governs helpers you have already chosen to document.)
- Do not document `self` or `cls`.
- Do not restate defaults obvious from the signature unless the default has
  semantic importance.
- Use `Yields:` when the caller consumes the result as a stream; use `Returns:`
  for a single value. Describe what the caller observes, not how the function is
  implemented — a `pipe` that is `return parser(...)` still uses `Yields:`,
  because every `pipe` hands back an iterator (see "The two returns of a pipe").
- The summary names what the helper is *for*; the output description belongs in
  `Returns:`/`Yields:`, never in the summary. So do not lead with `Returns`/
  `Yields` (see the rule above) and do not narrate the body:
  `"""Yields from stream, then closes f."""` both restates the section and
  describes the loop. Write `"""Passes stream through, closing f when iteration
  ends."""` plus a `Yields:` section naming the element.
- Classes document the abstraction + constructor semantics; do not duplicate the
  class docstring in `__init__`. Give `__init__` its own docstring only for
  initialization behavior not reasonably documented on the class.
- Properties document the exposed value as a noun, not a getter
  (`"""Whether the source stream has been fully consumed."""`).
- Exception classes stay short — usually a single line.
- Declarative type objects (`TypedDict`, `Protocol`, enum, dataclass) document the
  concept in prose/`Attributes:`; no invented doctests for objects with no runtime
  behavior worth demonstrating.
- Most straightforward dunders need no docstring when the class already defines
  the behavior; cross-reference (`equivalent to :meth:\`run\``) instead of
  duplicating.

## Doctest rules

Every `>>>` block anywhere — Python source, `README.rst`, or `docs/*.rst` — is
executable test code (`--doctest-modules` + `--doctest-glob=*.rst`). Never use
`>>>` for illustrative pseudocode; if an example must not execute, use a plain
code block without interpreter prompts.

- Treat doctests as executable user documentation first, tests second.
- Show actual returned values, not boolean assertions
  (`>>> next(pipe(items))["count"]` → `5`, not `... == {"count": 5} → True`).
- Follow Arrange → Act → Observe; keep each example focused on one behavior.
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
  ...     result = await async_pipe(items)
  ...     print(next(result))
  >>>
  >>> run(main)
  ```

  Those two positions only — no other empty prompts for visual spacing. A true
  blank line still terminates the example, so it can never substitute for `>>>`.
- Prefer double-quoted strings in example **input**; expected dict/`repr` output
  keeps whatever Python actually prints (usually single quotes).
- Public examples exercise the public object — do not reach through the API into
  private helpers.
- Private-object doctests are rare; use one only when a compact executable
  example significantly clarifies non-obvious behavior.

## Python syntax baseline

Use idiomatic Python 3.12+:

- PEP 604 unions: `X | Y`
- built-in generics: `list[str]`
- PEP 695 type parameters where appropriate
- modern asyncio / AnyIO patterns

**There is no Twisted anywhere.** The optional async backend is AnyIO. Document
the async contract, not the machinery. The canonical async doctest form is:

```python
Examples:
    >>> from riko import run
    >>> async def main():
    ...     items = ({"x": x} for x in range(5))
    ...     result = await async_pipe(items)
    ...     print(next(result))
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
  semantics — not how every exported object works.
- Keep package doctests minimal; tutorials belong in `README.rst`/`docs`.

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
data. Use `require_kwarg` (`riko/modules/_prepare.py`), which names both the
pipe and the argument, and document it under `Raises:`.

```text
Bad:   KeyError: 'func'
Good:  TypeError: the 'aggregate' pipe requires the 'func' keyword argument
```

The dividing line is whether an identity behavior exists that leaves the data
honest. A *modifier* has one; the *operand* the pipe exists to apply does not.
The four operand cases are `aggregate`/`udf` (`func`), `join` (`other`), and
`send` (`others`).

## Reserved terms

Some words already name a specific riko concept. Using them loosely sends the
reader to the wrong place.

| Term | Means | Say this instead |
|---|---|---|
| **coroutine** | `riko._pubsub.coroutine` — a *generator* coroutine primed for `.send()`, used by the `send`/`receive` pub/sub pipes. **Not** async. | "async function" for anything `async def` |
| **stream** | an iterator of items | don't use it for a single item |
| **item** | one dict-like record | don't use it for a stream |
| **pipe** | a configured module | don't use it for the `parser` |

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
