# Correctness audit — carrying the module sweep to the rest of the repo

## 1. Mission

The `riko/modules/*.py` documentation sweep (all 52 pipes, standard in
[DOCUMENTATION_STANDARD.md](../DOCUMENTATION_STANDARD.md)) was nominally about docstrings.
In practice most of its value came from *running* each pipe to verify what the docs
claimed, which surfaced a steady stream of real defects — frozen clocks, fabricated
values, unreachable error paths, config keys that did nothing.

Those defects were not module-specific. They are recurring shapes, and the ~55
non-module files under `riko/` have never had the same treatment. This plan carries
the method and the taxonomy forward.

**This is an audit plan, not a rewrite plan.** Every item is "verify by execution, then
fix or record" — not "restructure".

## 2. The method

The sweep's one transferable lesson: **reading code does not find these; running it
does.** Concretely, for each unit under audit:

* Call it with the edge inputs — missing key, `None`, `""`, `0`, unparseable text,
  wrong type — and look at what comes back, not at what the code appears to do.
* Verify every documented default by executing it. Six were wrong in `riko/modules/`,
  including `emit` defaults documented as the opposite of reality.
* Read enumerations at runtime (`[m.value for m in SomeEnum]`), never from a piped or
  truncated `grep`. A truncated grep produced a false claim during the sweep and cost a
  broken working tree.
* Run twice with different `PYTHONHASHSEED` when ordering is involved.
* Diff the sync and async halves of any pair; they drift.
* Use `git log -S"<symbol>"` to distinguish *vestigial* (once worked) from
  *never-implemented* (never read in any commit). The fix differs.

## 3. Defect taxonomy

Each class below was found more than once during the sweep. The example is real, the
detection recipe is what actually found it, and the fix is the pattern that was applied.

### C1 — import-time capture of runtime state

A module-level constant freezes the clock, the environment, or the filesystem at import,
then gets used as if it were live.

* **Found:** `rssitembuilder.DEFAULTS = {"pubDate": NOW.isoformat()}` stamped every item
  with the *process start* time. `datebuilder.SWITCH` froze `today`/`tomorrow`/
  `yesterday`/`now`, so a long-running process resolved `"today"` to the day it booted.
  `exchangerate.PARAMS` reads an API key from the environment at import.
* **Detect:** grep module-level assignments for `NOW`, `TODAY`, `getenv`, `now()`,
  `date.today()`, `Path.cwd()`. Anything that stamps or resolves *data* is suspect;
  epoch-style constants are fine.
* **Fix:** resolve per call. A plain `DEFAULTS` dict cannot hold a lazy value, so the
  call moves into the parser.

### C2 — unreachable or self-defeating code

A guard exists and looks right, but can never fire or repairs nothing.

* **Found:** `datebuilder`'s `raise ValueError("Unrecognized date string")` was dead,
  because `parse_date_string` raises rather than returning `None` — so callers saw
  `dateutil`'s `ParserError` instead. `currencyformat`'s `amount is None` branch was
  unreachable (the cast defaults to `NaN`, never `None`). Best of the set:
  `def_itemgetter`'s `if isnan(casted): casted = default` — where `default` *was* `NaN`,
  so it replaced NaN with NaN and `float` sorts silently returned input order.
  A second shape is the repair that is computed and then thrown away:
  `get_regex_rule` filtered a raw rule down to the dataclass's fields and called
  `RegexConfRule(**filtered)` without assigning it, so `rule` stayed a dict and the next
  line raised `AttributeError`. The suite missed it because every test reaches that
  function with a dataclass already — the dict branch had no coverage at all.
* **Detect:** branch coverage over the test suite; `git log -S` on the symbol; and for
  every guard, ask what value the remedy actually resolves to at runtime. When a
  function branches on input *type*, check that both branches are exercised — an
  untested branch is where this class hides.
* **Fix:** make the guard's remedy come from a different source than the problem.

### C3 — declared but never read

Config keys and parameters that exist in types, defaults, and docs but no code reads.

* **Found:** `regex.convert` (in `DEFAULTS`, in `RegexConf`, in four doctests — never
  read in any commit), `regex.singlematch`, `send.name` (copy-pasted from `receive`,
  and `Required`). The inverse also occurs: `urlbuilder.param` was documented optional
  but `extract` made it mandatory.
* **Detect:** for each key in `riko/types/modules.py`, grep for `objconf.<key>`,
  `rule.<key>`, `conf["<key>"]`, `kwargs.get("<key>")`. Then round-trip the other way:
  call the pipe *without* each documented-optional key. Grep the whole repo, not just
  `riko/` — `make_regex_rule` looked dead until `tests/pypipelines/` turned up ~50
  callers.
* **Fix:** delete — but see **C9** first.

### C4 — silent fabrication

The unit succeeds and returns a plausible-looking value instead of signalling absence.
The most dangerous class, because pipelines built on it look correct.

* **Found:** a missing date formatted as `01/01/1970 00:00:00`; a missing amount as
  `'$NaN.00'`; a missing `base` as the url `'None?s=gm'`; `"30 minutes"` parsed as
  *00:30 today* rather than now+30m; `geolocate`'s canned records for any input
  (see [enrichment-modules.md](enrichment-modules.md) § 6b).
* **Detect:** feed each unit a missing/`None`/garbage input and ask whether the output
  is distinguishable from real data. `""` and `NaN` are self-evidently empty; an epoch
  date, a `0`, or a canned record are not.
* **Fix:** degrade to the type's empty value (`""`) where the pipe emits text, to a
  detectable sentinel where it emits numbers, or raise a pipe-named error when the data
  contract cannot survive. Match the neighbours — see § 4 of
  [enrichment-modules.md](enrichment-modules.md) for the text-vs-numeric split.

### C5 — third-party errors leaking

An exception from a dependency escapes with a message that names neither riko nor the
offending config.

* **Found:** `slugify` with `separator=None` raised
  `TypeError: replace() argument 2 must be str, not None` from inside `python-slugify`;
  `dateformat` raised `AttributeError: 'NoneType' object has no attribute 'strftime'`.
* **Detect:** call every boundary that hands user config to a dependency with `None`
  and with a wrong type.
* **Fix:** the house pattern is `require_conf`/`require_kwarg` for programming errors
  (`TypeError: the 'x' pipe requires the 'y' conf key`) and `logger.warning` + degrade
  for data conditions. Never let the dependency's own message be the user's error.

### C6 — duplicated logic where one copy is weaker

* **Found:** `datebuilder` reimplemented a two-unit subset of `cast_datetime`'s
  relative-date parsing, with bare `timedelta` instead of `relativedelta`, and let
  everything it did not handle fall through to `dateutil`. Deleting it in favour of
  delegation *gained* `"next week"`/`"last month"` and fixed month arithmetic.
* **Detect:** look for two functions sharing a vocabulary (`today`, `days`, `weeks`).
  Compare their capability matrices, not their code.
* **Fix:** delegate to the richer implementation and move any capability the weaker one
  uniquely had *into* it, rather than keeping both.

### C7 — doc/runtime drift

* **Found:** `rssitembuilder` documented and FAQ-listed as a `source` while its runtime
  metadata said `transformer`; `tokenizer.emit` documented `False`, actually `True`;
  `dateformat.async_pipe` nesting `assign`/`field` inside `conf` where they are not
  read; `subelement`'s module docstring instructing a `path` that never matched.
* **Detect:** compare `get_module_metadata()` against `docs/FAQ.rst` and the docstrings;
  execute every documented default.
  The harder variant is **consensus drift**, where nothing disagrees: `urlbuilder`'s
  runtime metadata and the FAQ both said `transformer` and agreed with each other, so no
  cross-check could flag it — yet it is conf-driven, works with no input item, and is
  the twin of `itembuilder`/`rssitembuilder`, both sources. Only comparing it against
  *sibling modules of the same shape* surfaced it.
* **Detect:** compare `get_module_metadata()` against `docs/FAQ.rst` and the docstrings;
  execute every documented default. Then ignore all three and ask what the module
  actually is, by comparison with its nearest sibling.
* **Fix:** decide which side is right by behaviour, then correct the other. Prefer
  fixing the code when the docs, the FAQ, and a sibling module all agree against it.
  Reclassifying a processor as a source changes its `assign` default to `"content"` and
  moves it between discovery buckets, so it needs `gen-names`, the golden `_SOURCES` set
  in `tests/internal/test_codegen_names.py`, and the FAQ's module table and
  `list_modules(category='source')` count.

### C8 — non-determinism

* **Found:** `tokenizer`'s `dedupe` used a `set`, so token order changed with
  `PYTHONHASHSEED`; `NaN` sort keys made `sorted()` return input order.
* **Detect:** run under three `PYTHONHASHSEED` values; grep for `set(` in any path
  whose output order is observable.
* **Fix:** `dict.fromkeys` to dedupe in order; an orderable filler for sort keys.

### C9 — dataclass vs TypedDict before removing a field

**Check this before acting on C3.** A `TypedDict` is inert, so deleting a member is a
type-level change only. A `@dataclass` validates, so deleting a member turns
"silently ignored" into `TypeError: __init__() got an unexpected keyword argument` for
any existing config still carrying it.

* **Found:** removing `singlematch` from `RegexConfRule` (a dataclass) broke two real
  Yahoo Pipes fixtures. `send.name` and `regex.convert`, both `TypedDict` members, came
  out cleanly.
* **Fix:** for a dataclass, either strip the key from the fixtures/exports first and
  accept that stale configs now raise, or keep the field and mark it — the codebase's
  existing pattern is `SortConfRule.cast: bool = False  # Not implemented`.
* **Better: make the boundary tolerant.** Any `SomeDataclass(**raw_dict)` turns an
  unrecognized key into a hard failure. `get_regex_rule` now filters to
  `{f.name for f in fields(RegexConfRule)}` first, so an export carrying an option riko
  never implemented still loads. Audit every such construction — `grep -rnE
  "[A-Z][A-Za-z]+\(\*\*[a-z_]+\)" riko/` currently finds `_strutils` only, but the
  same shape will recur wherever raw config meets a dataclass.

### C10 — omitted conflated with an explicit `None`

A call site that never mentioned a parameter is indistinguishable from one that passed
`None`, so the "default" path overwrites state the caller meant to keep, or invents a
criterion the caller never supplied.

* **Found:** `PyPipe.__call__` writes `conf=None`/`context=None`/`inputs=None` into
  `self.kwargs` for every kwarg the caller omitted (§ 8 **R2**); `get_skip` does
  `if text := str(_skip.get("text")):`, so an absent `text` becomes the truthy literal
  `"None"` and starts matching real content (**R12**); `listize=True` skips falsey
  pieces because the guard is `if pieces and opts.get("listize")` (**R13**);
  `gather_results` filters `r is not None` to mean "not finished" (**R7**).
* **Detect:** for every `x or default` / `if x:` / `str(x)` over a user-supplied value,
  ask what `0`, `False`, `""` and a deliberate `None` do. Call each entry point twice —
  once omitting the argument, once passing `None` — and diff the results.
* **Fix:** a module-level sentinel, the same pattern as `rename`/`regex`'s `_MISSING`
  (see `CLAUDE.md` § "Absent field ≠ present-`None`"). Never let `None` carry two
  meanings; never let truthiness stand in for presence.

### C11 — a lazy stream consumed eagerly

The unit is documented as streaming, and the sync happy path over a list looks right,
but an iterator input is drained before the first output appears — so an unbounded
source hangs and a large finite one is retained whole.

* **Found:** keyed `join` builds `product(stream, other)`, and `itertools.product`
  tuples **both** inputs, so the primary stream is materialized even though the module
  contract says `other` is the replayed side (§ 8 **R3**); async `send` appends every
  item to `sent` and returns `iter(sent)` after `complete` (**R4**); the non-memoized
  text branch of `_io.opener` requests with `stream=False` and then reads `r.raw`
  (**R1**); `AsyncTimeoutIterator` only checks its deadline *between* `anext` calls, so
  a stalled source is never bounded (**R14**).
* **Detect:** feed the unit `itertools.count()` (or any generator that logs each pull)
  and assert a first output arrives. Assert on *time to first item*, not just on the
  final list. Grep for `product`, `list(`, `sorted(`, `tuple(` on the primary stream.
* **Fix:** retain only the side the contract says is retained, and yield inside the
  loop. Where a deadline is involved, bound the *await* (an AnyIO cancel scope with the
  remaining deadline), not the interval around it.

### C12 — sync/async divergence

The pair shares a name, a docstring and a config, but the two halves resolve values,
bound waits, or release resources differently — so a pipeline behaves differently purely
by execution mode.

* **Found:** sync `send` yields as it publishes while async `send` buffers (**R4**);
  `async_url_open` decodes with the caller/default encoding and ignores the HTTP charset
  while `async_url_read` ignores its explicit `encoding` and returns `response.text`,
  and `fetchpage.async_parser` never forwards `objconf.encoding` at all (**R15**);
  sync `receive` honors `max_wait` and async does not
  ([execution-semantics.md § 7.1](execution-semantics.md#71-receive-has-no-async-timeout)).
* **Detect:** run the same conf through `pipe` and `async_pipe` and diff the outputs,
  including on the edge inputs of § 2. Diff the two implementations side by side — the
  divergence is usually one missing argument, not a different algorithm.
* **Fix:** one resolution order, stated once and shared. For encoding that order is
  explicit conf → response charset → `ENCODING` default; for waits it is the same
  `on_timeout` policy on both sides.

## 4. Scope — the un-swept surface

`riko/modules/` is done. Group the rest by risk, highest first.

| Area | Files | What to look for |
|---|---|---|
| Cast & coercion | `cast.py`, `_iterutils.py`, `dates.py`, `_date_utils.py` | **C4** above all — this layer decides what a missing value becomes, so its defaults propagate everywhere. **C2** in every guard. |
| Types & config | `types/*.py` | **C3** exhaustively, then **C9** before deleting. Doc-hint defaults (`= 5`) that disagree with the module's real `DEFAULTS`. |
| Parsing & IO | `parsers.py`, `_io.py`, `_rssutils.py`, `_strutils.py`, `autorss.py`, `_reencode.py` | **C5** (lxml, requests, feedparser), **C4** on malformed input. Note `_strutils.make_regex_rule` is *not* dead — it has ~50 callers in the hand-written `tests/pypipelines/*kazeeki*.py`, which is itself worth a look: those import a **private** module, so `_strutils` is effectively part of the pipeline-authoring surface. |
| Core runtime | `collections.py`, `_decorators.py` (already partly covered), `context.py`, `dotdict.py`, `_objectify.py` | **C7** against `RUNTIME_CONTRACT.md`, **C2** in the assignment/lifecycle guards. |
| Async | `bado/*.py`, `_pubsub/*.py` | **C6** against AnyIO (owned by [bado-anyio-alignment.md](bado-anyio-alignment.md)), sync/async behavioural parity. |
| Extension & CLI | `ext/*.py`, `cli/*.py`, `compile.py`, `topsort.py` | **C3**, **C7**. Known: `describe_module` shipped with three always-`None` fields because nothing exercised them. |

## 5. Phases

* **A0 — config-key census.** Mechanical and highest value per hour: every key in
  `types/modules.py` cross-checked against its readers, and every doc-hint default
  against the module's `DEFAULTS`. Produces a delete/keep/fix list. Apply **C9** per row.
* **A1 — cast & coercion.** The `CAST_SWITCH` defaults, `_resolve_default`, and every
  guard in `_iterutils`. Carries the open decision in
  [enrichment-modules.md](enrichment-modules.md) § 6c (settable timezone).
* **A2 — parsing & IO boundaries.** C5 sweep over every dependency call; decide
  whether `_strutils` helpers used by hand-written pipelines belong on a public surface.
* **A3 — core runtime.** Behaviour verified against `RUNTIME_CONTRACT.md` §§ as written,
  not as remembered.
* **A4 — async parity.** Sequenced after / with `bado-anyio-alignment.md`.
* **A5 — extension & CLI.**

Each phase lands with: fixes for unambiguous defects, a `docs/CHANGES.rst` entry per
behaviour change, a regression test *verified to fail before the fix*, and a
`CLAUDE.md` invariant for anything a future reader would otherwise "clean up" back.

The § 8 register is the concrete work list for these phases — each row carries the
phase that owns it. The three **P0** rows do not wait their turn: they gate the
`features` → `main` merge
([release-readiness § 9.1](release-readiness.md#91-merge-gate-features--main)).

## 6. Testing posture

The sweep settled three test kinds; keep them distinct, because they fail for different
reasons and want different responses.

* **Regression** — pins a fixed bug. Must be verified failing before the fix.
* **Tripwire** — pins behaviour that is *correct today* but that a planned change could
  silently break. Simulate the planned change to prove the tripwire catches it.
* **Characterization** — pins behaviour that is *wrong today* and slated to change, so
  the change cannot slip through a green suite. Its docstring must say it should be
  **updated, not deleted**, when the behaviour changes.

Do not pin behaviour that is merely arbitrary (tie order among equal sort keys); that
cements what a fix means to change.

## 7. Definition of done

1. Every config key declared in `types/` is read, or deleted, or marked unimplemented.
2. No unit fabricates a value indistinguishable from real data on missing input.
3. No dependency's exception reaches a user without a riko-owned message.
4. No module-level constant captures runtime state used as if live.
5. Output order does not depend on `PYTHONHASHSEED`.
6. Documented defaults match executed defaults, repo-wide.
7. Each fix has a regression test that was verified to fail beforehand.
8. Every § 8 register row is fixed, or downgraded to an accepted behaviour pinned by a
   characterization test that says what would change it.
9. No unit that documents streaming drains its primary input before the first output.

## 8. Open defect register — `features` branch audit

A static correctness pass over the **non-module** runtime (I/O, wrappers, compiler,
sync/async execution, parsing, extension resolution) on `features` @ `d8d3c02`. It is
the first evidence that § 4's ranking was right: nearly every row lands in an un-swept
area, and none of them break a happy-path test. Each row below was **re-verified
against the tree on 2026-08-23** — the audit's own claims got the § 2 treatment before
being written down, which is why two of its findings are recorded here as *not
reproduced*.

`Class` is the § 3 taxonomy; `Phase` is § 5; `Owner` is the gameplan that holds the
design when the fix is more than a local repair.

| # | Pri | Where | Defect | Class | Phase | Owner |
|---|:---:|---|---|:---:|:---:|---|
| R1 | ~~P0~~ **fixed** | `_io.py:271` | Non-memoized **text** fetch requested with `stream=False` (`stream=binary`) then read the already-consumed `r.raw`. Reproduced against a local server: it does not return an empty body, it raises a bare `StopIteration` from meza's `Reencoder.__init__` straight out of `Fetch` (uncaught — neither `RequestException` nor `URLError`). Fixed by `stream=not memoize`; regressions in `tests/internal/test_io.py`, verified failing first. | C11 | A2 | — |
| R2 | P0 · **deferred** | `collections.py:519` | `PyPipe.__call__` writes every omitted kwarg into `self.kwargs` as `None`, and never syncs `self.conf`/`self.context`/`self.inputs` — so `p(assign="x")` drops the constructor `conf`, and `p(conf=new)` leaves `p.conf` disagreeing with what executed (`_prime` reads the attributes, `__call__` reads the kwargs). **Decided 2026-08-24: not patched here** — the `Pipeline`/`Execution` split deletes the class, so the fix is immutable reconfiguration in the new API, not a sentinel on a doomed one. **Stays live until the split lands.** | C10 | — | [MILESTONES § split](../MILESTONES.md) (rules + exit tests) · [release-readiness § 9.1](release-readiness.md#91-merge-gate-features--main) |
| R3 | ~~P0~~ **fixed** | `join.py:124,129` | `product(stream, other)` tuples **both** inputs, so the primary stream was materialized despite `other` being the documented replayed side; `join(count(), other)` never emitted. The keyless natural join had the **same** defect one level down — `meza.process.join` is `map(merge, it.product(left, right))` — so both branches were fixed: `others = list(...)` + a nested lazy loop; `meza.process.join`/`itertools.product` no longer imported. Output order unchanged. Regressions in `tests/public/test_pipe_implementations.py`, verified failing first (they hung). They assert **bounded** consumption, not zero: the operator wrapper reads one item ahead of the parser. | C11 | A3 | [feed-native § 2](feed-native-streaming.md#2-per-pipe-audit) |
| R4 | P1 · **partly fixed** | `send.py:80` | `async_parser` buffers into `sent` and returns `iter(sent)` after `complete`; sync `parser` yields per item. Unbounded sources never return, finite ones duplicate the stream in memory — on the one pipe whose purpose is lazy fan-out. **Two adjacent defects fixed 2026-08-24:** (a) `complete` sat *after* the loop, so a `ReceiverUnavailableError` from `publish` skipped it and every healthy receiver blocked forever on a channel nobody would close — now in a `finally`; (b) the loop was a sync `for`, so the `AsyncIterator` that `operator.aparse`/`setup` legitimately produce raised `TypeError: 'async_generator' object is not iterable` — now iterated via `bado.itertools.async_iter`. Both regressions in `tests/public/test_pipe_implementations.py`, verified failing first (a hung to the timeout marker, b raised). **The buffering itself is deferred to F1, not A4** — yielding lazily requires `async_parser` to be an async generator, and the operator wrapper's post-parser path is sync-only *and fails silently*: an async gen isn't awaitable (`_decorators.py:1050`), so `isinstance(stream, Iterator)` is `False`, `get_assignment` (`_assignment.py:110`) takes its `else` branch and emits the generator **object** as a single item. Guard test landed as a `strict` xfail so it flips when F1 lands. | C11 · C12 | ~~A4~~ **F1** | [fanout-topology § 5](fanout-topology.md#5-phase-f1--make-async-receive-truly-streaming) |
| R5 | P1 | `compile.py:302` | `pythonise` replaces four characters and ASCII-`replace`-encodes, so `"class"`, `"my module"`, `"foo.bar"`, `"1st"`, `"café"` all survive into generated source as identifiers. A pipeline that runs through `build_pipeline` can fail to compile. `ext/codegen.py:59`'s `enum_member_name` already does this properly. | C6 | A5 | [module-enums § P9A.7](module-enums.md#p9a7--one-identifier-sanitizer) |
| R6 | P1 | `_serialize.py:231` | The unsupported check is shallow (`_UNSUPPORTED in hashable_args`) while `_to_hashable` substitutes **recursively**, so `cached({"x": Opaque()})` calls the wrapped function with `{"x": _UNSUPPORTED}` and every `Opaque()` collapses onto one key. Argument corruption, not a cache miss. Return `(supported, value)` from `_to_hashable`, or scan recursively before `_cached`. | C4 | A3 | — |
| R7 | P1 | `bado/_util.py:68` | `gather_results` returns `[r for r in results if r is not None]`, so a legitimate `None` result is dropped and the list no longer aligns with its inputs. `async_map`'s `_missing` sentinel is the house fix. | C10 | A4 | [bado-anyio § 2](bado-anyio-alignment.md#2-helper-audit-all-confirmed-present-in-the-current-tree) (already slated for replace/delete) |
| R8 | P1 | `_reencode.py:66` | `read(n)` is `islice(self.stream, n)` — `n` *iterator elements*, not characters/bytes, so `read(1)` over a line iterator returns a whole line. `read(0)` is fixed; bounded reads are not. Needs a remainder buffer so a partially consumed chunk carries forward. | C7 | A2 | — |
| R9 | P1 | `fetchtable.py:91,134` | The module advertises xls(x)/mdb/dbf/sqlite, but both halves open the resource as **text** (`Fetch(url, encoding=…)` / `async_url_open(url, encoding=…)`) before handing it to `meza.io.read`. An xlsx is a zip; decoding it first cannot work. Needs format-dependent binary handling. | C7 | A2 | [connectors.md](connectors.md) |
| R10 | P1 | `fetchdata.py:82,124` · `fetchtable.py:96,137` | `splitext(url)[1]` runs against the whole URL, so `…/export.json?token=abc` mis-detects. Want `splitext(urlparse(url).path)[1]`. Disproportionate for signed/authenticated export URLs — exactly the API-automation direction riko is moving in. | C4 | A2 | [connectors.md](connectors.md) |
| R11 | P2 | `dates.py:92` · `_date_utils.py:107` | `tt_to_datedict` derives `_tzinfo` from the tuple but computes `"utime": timegm(tt)`, and `timegm` reads the fields as UTC — an aware `+03:00` timestamp gets the 12:00-UTC epoch. Build an aware datetime and call `.timestamp()`. Related: `TZINFOS = dict(gen_tzinfos())` snapshots abbreviations **at import**, and duplicates (`CST`) overwrite each other. | C4 · C1 · C8 | A1 | — |
| R12 | P2 | `parsers.py:778` | `if text := str(_skip.get("text")):` turns an absent criterion into the literal `"None"`, so `{"content": "none available"}` can be skipped by a rule that specified only `field`. Check the raw value before converting. | C10 | A2 | — |
| R13 | P2 | `_prepare.py:141` | `if pieces and opts.get("listize")` means `0`/`False`/`""` stay scalars under `listize=True`, which the `listize + objectify` path then tries to iterate. Branch on `opts["listize"]`; special-case `None` only if `None` is meaningfully distinct. | C10 | A3 | — |
| R14 | P2 | `timeout.py:99` | `AsyncTimeoutIterator.__anext__` checks the clock either side of `await anext(...)`, so a source that stalls forever is never bounded — the deadline holds only while items keep arriving. Needs a cancel scope carrying the **remaining** deadline. | C11 · C12 | A4 | [execution-semantics § 7.2](execution-semantics.md#72-a-blocked-anext-outlives-the-deadline) |
| R15 | P2 | `bado/io.py:114,131` · `fetchpage.py:96` | `async_url_open` decodes with the caller/default encoding and ignores the HTTP charset; `async_url_read` ignores its explicit `encoding` for HTTP and returns `response.text`; `fetchpage.async_parser` forwards no encoding at all. Four paths decode the same bytes four ways. | C12 | A4 | [bado-anyio § 2c](bado-anyio-alignment.md#2c-encoding-resolution-precedence-syncasync-parity) |
| R16 | P3 | `csv.py:93,135` · `fetchtable.py:94,135` | `seekable()` documents that its spooled replacement leaves the original open, but both callers `auto_close` the spool only — the HTTP response leaks when `has_header=False`. | C2 | A2 | — |
| R17 | P3 | `compile.py:854` | *Not reproduced.* `convert_dag` on an empty module list was reported to reach `module_ids[-1]`; the terminal `output` node is appended unconditionally, so it does not. Still worth an explicit empty-DAG rejection rather than relying on that. Pin with a characterization test before changing. | — | A5 | — |
| R18 | P3 | `ext/resolver.py:39` | `name.startswith(("pipe_", "pipe:"))` routes to the pipeline resolver unconditionally, so a registered **leaf** extension named `pipe_transform` can never resolve through `ModuleRegistry`. Either reserve the prefixes at registration time or try registered modules first. | C7 | A5 | [extensibility § 24](extensibility.md#24-module-registry-and-plugins) |
| R19 | P3 | `filter.py:76` | `NUMERIC_OPS = {"atmost", "atleast"}`, so `greater`/`less` over string values compare lexicographically (`"10" < "9"`). Whether that is a defect depends on the Yahoo Pipes compatibility contract — **characterize first, decide second**. | open question | A3 | — |

**What the shape of this register says.** The finite/list/file-fixture paths are covered;
the defects cluster in iterator exhaustion, unbounded streams, falsey values, nested
objects, real HTTP behaviour, binary formats, and sync/async parity — which is precisely
the coverage gap [testing.md § 2b](testing.md#2b-regression-batch-from-the-branch-audit)
now owns.
