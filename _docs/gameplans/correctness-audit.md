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
