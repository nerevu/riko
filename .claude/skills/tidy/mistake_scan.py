"""
Scan riko for the defect classes past bug-fix sessions kept repairing.

Purpose: catch a new instance of a mistake class this repo has already paid to fix,
before it lands. The classes were mined from the 79 ``[FIX]`` commits (and fixups)
since v0.77.3 and the triage notes of 2026-10-05, 10-28/29, 10-30, and 10-31. Each
class's refs cite its fixes by short sha; ``NON_BEHAVIORAL`` lists the fixes that
changed no behavior (typos, type errors, line length, tool config, script restores).

Rules (code, class, what it flags):

    RM101 truthiness  ``x or default`` where ``x`` is a value (``0``/``""`` valid);
                      ``x and f(x)`` that guards a value (or a lambda parameter)
                      and then reuses it
    RM102 truthiness  ``if x:`` / ``if not x:`` / a comprehension ``if x`` on a
                      value-like name; ``bool(x)`` or ``not x`` on one inside an
                      expression
    RM103 stopiter    one-argument ``next(it)`` in a generator, outside ``try``
    RM201 hash-order  builtin ``hash()``; iterating, materializing, or splatting a
                      set without ``sorted``
    RM301 last-wins   ``json.load(s)`` without ``object_pairs_hook``
    RM401 close       only a ``Generator``/``AsyncGenerator`` is closed (no
                      ``else`` branch closes the rest)
    RM402 close       a user callback's result is discarded (an awaitable never runs)
    RM403 close       ``async for`` over a call in an async generator, without
                      ``aclosing``
    RM404 close       a bare ``.close()`` on a ``cast(...)`` or a generic-typed
                      parameter (its ``close()`` may be async and return a
                      coroutine that never runs)
    RM501 decode      ``.decode()`` on a chunk/line/raw value (use an incremental
                      decoder)
    RM502 find-slice  a ``.find()``/``.rfind()`` result sliced with no ``-1`` check
    RM601 unbounded   a ``timeout``/``grace`` parameter defaulting to ``0`` or ``inf``
    RM701 frozen      a frozen record field typed set/list/dict, or typed frozen with
                      no ``converter=``
    RM801 parity      sync/async twins (``x``/``ax``, ``_x``/``_ax``) passing
                      different I/O keywords (``timeout``, ``encoding``, ...)
    RM802 colors      an ``async def`` method of ``AsyncX`` named exactly like a plain
                      ``def`` method of its twin ``X``/``SyncX`` (same file first,
                      else anywhere under ``riko/``); prefix it ``a``. Dunders and an
                      ``AsyncX`` subclassing its twin are skipped
    RM1001 kwarg-shadow  a ``**kwargs`` function whose parameters a same-file
                      ``partial``/``async_partial`` binds by position but a forwarded
                      keyword could also name (make them positional-only, ``/``)
    RM1101 bad-config  a decimal-domain handler (naming ``InvalidOperation``) that
                      catches ``ValueError`` but not ``OverflowError`` around a
                      callable chosen at runtime (it may ``int()`` an infinite value)
    RM1102 bad-config  an ``_env_int``/``_env_bound`` ``RIKO_*`` read with no
                      ``minimum=`` (an out-of-range value is kept)
    RM901 multi-return  a function with more than one ``return`` (the house style is
                      a single return at the end); each ``return`` is a lead, so a
                      change to any of them is in scope

Classes with no rule (``equivalent-spellings``, ``races``, ``mixed-input``, and the
other probe-only classes ``--classes`` lists) carry only an audit probe in
``CLASS_HISTORY``: their pre-fix lines show no shape a line scan can tell from correct
code. ``--classes`` lists every class with its rules or probe.

Known gaps, found by running the rules on the pre-fix files: RM404 sees only a
receiver typed in the same function, so a generic value reached through an attribute
or a local slips past; an empty CSV fails inside meza; the exchangerate timeout rode
``Fetch``'s default, so RM801 never saw it (the planned sync/async parity test
covers it). RM301 covers only the JSON-document surface of "last-wins"; most of that
class's history is registry and id collisions, now guarded by ``Registry`` and tests.
``--since`` merges ``REF...HEAD`` with the working-tree diff, so line numbers can drift
when uncommitted edits sit above a committed hunk. RM1001 sees only partials in the same
file, and its lead sits on the ``def`` line, so a fix that only adds ``/`` replays with
no lead (``replay_fixes.sh`` scans the pre-fix lines). RM1101 fires only when the
guarded call is chosen at runtime (a parameter, a local, or a subscripted lookup): a
named function's errors are its documented contract, so it raises its own ``ValueError``
rather than every caller catching ``OverflowError``.
The ``RIKO_ENCODING`` fix (an ``_env_str`` read never validated) has no shape distinct
from a free-text setting, so it is a probe, not a rule. RM502 sees only
``find()``/``rfind()``: an unchecked ``removeprefix()`` (the legacy-port fix) is legal
on its own, so it is a probe, not a rule.

Out of scope (needs a type checker or a run): lying overloads and guards that narrow
to ``Unknown`` (``reveal_types.py``); sync/async output parity (a harness run); a fix
later undone by a refactor (``.claude/skills/triage/fail_first.py``).

Inputs:
    default        lines changed in the working tree vs HEAD, plus untracked files
    --diff-file F  lines a saved unified diff adds (``-`` reads stdin, following the
                   pointer ``gates.py scope tidy`` prints for a large scope)
    --staged       lines changed in the index
    --since REF    lines changed in ``REF...HEAD`` plus the working tree
    --all          every line (expect already-triaged leads; use ``--rule``)
    --rule CODE    only these rule codes or prefixes (repeatable: ``--rule RM1``)
    --tests        also scan ``tests/``
    --classes      print the class table instead of scanning: per class, ranked by fix
                   count, its rule codes (or ``probe-only``), count, refs, an audit
                   ``probe:`` and the ``safe:`` shapes ruled not to be defects
    --unclassified lists the ``[FIX]`` commits since the last tag (or ``--since REF``)
                   that no class's refs and no ``NON_BEHAVIORAL`` entry cite, one
                   ``sha subject`` per line; exits 1 when any is listed
    --status SHA   prints each fix's replay status, one ``sha status`` line per sha
                   (repeatable, or several after one flag): ``non-behavioral``,
                   ``probe-only`` (cited only in classes with no rule), ``explained``
                   (each ruled class's ref carries a ``;`` note), ``unexplained`` (a
                   ruled class cites it with no note), or ``uncited``; ``probe-only``
                   appends ``: class, ...`` (every citing class), ``explained`` the
                   ruled classes, and ``unexplained`` the ruled classes whose ref needs
                   a note
    --rewrap       rewrite this file's ``CLASS_HISTORY`` source with every string
                   re-wrapped to 88 columns (run after adding a ref; then
                   ``ruff format``)
    --remap        repair refs after a rebase: a cited sha HEAD no longer reaches
                   becomes the one same-subject commit since it forked, and an
                   ``uncommitted (MM-DD note)`` ref takes the sha of the
                   ``--unclassified`` fix (or ``--since REF``) authored that day whose
                   patch holds the most of the note's identifiers (backticked words,
                   ``snake_case`` names, ``name()`` calls); prints each ref it could not
                   place and exits 1 when any is left
    paths          restrict to these files/directories

RM901 is a style rule, not a mined defect class: it has no fix history and sorts
last. Nested functions, lambdas, and classes count their own returns.

Truthiness and frozen-record rules skip ``riko/cli`` (flags and argv, not data).
Suppress a reviewed site with a trailing ``# mistake-ok: RM101`` comment, not
``noqa``: ``ruff --fix`` strips unknown ``noqa`` codes.

Outputs: leads grouped by class, most-often-fixed class first (``CLASS_HISTORY`` cites
each class's fixes, and its fix count is derived from them; /triage adds a ref when a
fix lands), one ``path:line: CODE: message | source`` per lead, then per-class counts on
stderr. Exits 1 when any lead is reported.

Origin: /audit of the bug-fix sessions on 2026-11-01 (58bc2070 sibling re-audit,
84c7f004 close landscape, 05a01114 ijson, f5eeae62 meza), promoted to /tidy the same
day.

Run:

    python .claude/skills/land/gates.py scope tidy \\
        | python .claude/skills/tidy/mistake_scan.py --diff-file -
    python .claude/skills/tidy/mistake_scan.py --since main
    python .claude/skills/tidy/mistake_scan.py --classes
    python .claude/skills/tidy/mistake_scan.py --unclassified
    python .claude/skills/tidy/mistake_scan.py --remap

Smoke tests: uv run --active pytest .claude/skills/tidy/test_mistake_scan.py --no-cov
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from collections import Counter
from functools import cache
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

type _Methods = dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
type ReplayStatus = Literal[
    "non-behavioral", "probe-only", "explained", "unexplained", "uncited"
]

_NONE_RECORDED = "none recorded yet"
_REF_GROUP = re.compile(r"\(\d\d-\d\d ([^()]*(?:\([^()]*\)[^()]*)*)\)")
_CITED_GROUP = re.compile(rf"\b([0-9a-f]{{7,40}}) {_REF_GROUP.pattern}")
_RULE_ROW = re.compile(r"^ {4}(RM\d+) (\S+) ", re.MULTILINE)
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
_NOTE_TOKEN = re.compile(r"`(\w+)`|(\b\w*_\w+)|(\w+)\(\)")
_UNCOMMITTED = re.compile(
    r"uncommitted (\((\d\d-\d\d) ([^()]*(?:\([^()]*\)[^()]*)*)\))"
)
GIT = shutil.which("git") or "git"
ROOT = Path(__file__).resolve().parents[3]
GENERATED = {"_configs.py", "_names.py", "_module_ids.py"}
SAVED_DIFF = re.compile(r"written to (\S+);")
SUPPRESS = re.compile(r"#\s*mistake-ok:\s*([A-Z0-9, ]+)")
VALUE_NAME = re.compile(
    r"(count|limit|timeout|offset|start|stop|end|length|value|default|port|seed|key|"
    r"field|replace|sep|delim|num|index|idx|amount|step|width|size|delay|interval|"
    r"text|content|prefix|suffix|assign|func|match|repl|precision|places|base|max|"
    r"min|attr|path|ext|query|format|encoding|emit|newval|inputs|item|rule|word)",
    re.IGNORECASE,
)
PREDICATE = re.compile(
    r"^_?(is|has|can|should|use|allow|enable|strict|native)[_A-Z]|^_?(is|has)$"
)
BOOLISH = re.compile(
    r"(^|_)(flag|enabled|ok|done|closed|closing|found|seen|verbose|debug|test|async|binary|native|strict|emit|multi|reverse|recursive|lazy|dry|keepends|mode|seed)$|_is_|_has_|(match|ed|ing)$",
    re.IGNORECASE,
)
EMPTY_DEFAULTS = {
    "''",
    '""',
    "{}",
    "[]",
    "()",
    "0",
    "False",
    "None",
    "set()",
    "dict()",
    "list()",
    "tuple()",
}
CALLBACK_NAME = re.compile(
    r"^_?(cleanup|callback|hook|on_[a-z_]+|factory|finalizer|teardown)$"
)
GENERIC_ANNOTATIONS = {"object", "Any"}
CHUNK_NAME = re.compile(
    r"(chunk|raw|piece|block|part|line|buf|data|content|payload)", re.IGNORECASE
)
IO_KEYWORDS = {
    "timeout",
    "encoding",
    "remove_BOM",
    "decode",
    "chunksize",
    "limit",
    "errors",
    "newline",
    "mode",
    "headers",
}
GENERATOR_TYPES = {"Generator", "AsyncGenerator", "GeneratorType", "AsyncGeneratorType"}
MUTABLE_TYPES = {
    "set",
    "list",
    "dict",
    "Set",
    "List",
    "Dict",
    "MutableMapping",
    "MutableSequence",
    "MutableSet",
    "bytearray",
}
FROZEN_TYPES = {
    "frozenset",
    "tuple",
    "FrozenDict",
    "AbstractSet",
    "Mapping",
    "Sequence",
}
SET_OPS = (ast.BitOr, ast.BitAnd, ast.Sub, ast.BitXor)
OVERFLOW_CATCHES = {"OverflowError", "ArithmeticError", "Exception", "BaseException"}
BOUNDED_ENV_READERS = {"_env_int", "_env_bound"}
TEST_PARENTS = (ast.If, ast.While, ast.IfExp, ast.Assert)
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
NON_BEHAVIORAL = (
    "9e0c0fbf",
    "ac572190",
    "501f0505",
    "98480a20",
    "6195a481",
    "6287676b",
    "c854d14b",
    "2ee7e72b",
    "a4f277be",
    "9a4d290f",
)


class BugClass(NamedTuple):
    refs: str
    probe: str
    safe: str

    @property
    def count(self) -> int:
        """
        Counts the fixes ``refs`` cites.

        Each fix is a comma-separated item inside a date-prefixed parenthetical
        (``(10-31 regex, falsy func)`` cites two), up to the first ``;``, which starts
        a note on the group rather than another fix. Undated parentheticals (``none
        RM801-shaped (...)``) cite none.
        """
        groups = _REF_GROUP.findall(self.refs)
        return sum(len(group.split(";")[0].split(", ")) for group in groups)


CLASS_HISTORY = {
    "close": BugClass(
        (
            "0e46faa0 (09-30 async pipeline iteration; collected not streamed); "
            "abd4816b (10-28 async_url_open reentry; missing guard); 9e22c64c (10-29 "
            "sync pipe returns); 3361786b (10-29 node streams on early close; missing "
            "closes); 72a1b096 (10-30 async seed once); 47bf1190 (10-31 node streams "
            "once); 7ee178c7 (10-31 loop aclosing, async_merge aclosing); c6a3838c "
            "(11-01 owned values by type, raw return, async close()); d229b9b9 (11-03 "
            "unify closers); d7528227 (11-05 fetch responses; missing ExitStack); "
            "ef55b123 (11-13 async processor streams; missing early close); 5de5cc80 "
            "(11-19 adapted async-only streams, worker-thread embed drain; closer "
            "pairs); 5ce6bad4 (11-19 loop embed results; bare fold); 5de5cc80 (11-20 "
            "raw outputs at node start, run-owned async raw, portal-built async "
            "stream, splitter cascade at node start; cancellation window, failed "
            "iter); 909a7369 (11-22 async-only hand-through); 909a7369 (11-23 native "
            "async inputs, seed and root wrappers run-owned); 909a7369 (11-23 callable "
            "stream wrappers own their input); 6f4187b9 (11-25 cancelled aauto_close "
            "aclose stops before later closers; cancellation mid-close); 6f4187b9 "
            "(11-25 auto_close source whose iterator is a separate object; no close "
            "call); 6f4187b9 (11-25 auto_close skipped an async-only close silently); "
            "6f4187b9 (11-26 maybe_closing async-only)"
        ),
        (
            "end every value a function opens or receives on each exit path, error "
            "paths included; abandon an async iterator mid-stream and check its source "
            "closes"
        ),
        (
            "a `with`-managed value; a riko exception type as the closer's raises; "
            "`async_drain` leaving its source open (the exit stack owns seeds); an "
            "owned async stream's `aclose` bridged through the already-live portal; a "
            "real context manager's `__exit__` keeping its Python semantics"
        ),
    ),
    "truthiness": BugClass(
        (
            "098f7aa8 (09-01 skip text, gather None, listize falsy); 78952d53 (10-04 "
            "is-None fallbacks); e937e766 (10-05 port null); 0705f0cd (10-29 falsy "
            "input iterables); 7ee178c7 (10-31 regex, falsy func, rename '', DotDict "
            "''); 2bdc13e6 (11-11 skip_if presence); da63a1a3 (11-14 filter missing "
            "fields); 75dcdbd3 (11-25 gen_assignments yielded None read as empty; next "
            "default, not a falsy test)"
        ),
        'feed `0`, `False`, and `""` to every optional field and check each is kept',
        (
            "a `0` the docstring names as a sentinel; CLI flags/argv (`riko/cli` is "
            "skipped); `False` as the only opt-out of factory cleanup"
        ),
    ),
    "parity": BugClass(
        (
            "072730e2 (09-12 async kwargs drained; source shape); ef566c5e (09-30 "
            "async and awaitable sources; source shape); 85e25563 (10-28 async "
            "write/aggregate sources; source shape); cb4ab17d (10-28 async_write "
            "iterables; source shape); 0cfbfc62 (10-29 lazy async processor reads; "
            "source shape); 7ee178c7 (10-31 exchangerate timeout, ijson shape, "
            "async_write, async fetchpage/exchangerate encoding); 592972a2 (11-05 "
            "async HTTP status; status handling); 6dba2fe3 (11-17 split branches in "
            "both colors; branch behavior, no keyword drift); none RM801-shaped "
            "(source shape, status handling, not keyword drift); 6ad28467 (11-21 twin "
            "type/subtype/identity; attributes, not keywords); 6f4187b9 (11-25 native "
            "splitter list branches; branch type, not keywords)"
        ),
        (
            "run each sync/async twin on the same input, an error status and a bad "
            "encoding included, and diff outputs and raises"
        ),
        "raw entry keys that differ between feedparser and fastfeedparser",
    ),
    "last-wins": BugClass(
        (
            "e937e766 (10-05 parse_dag keys, alias collisions, id collisions, registry "
            "shadow); 39b93e99 (10-29 duplicate entry points; no JSON load); 05fd5672 "
            "(10-29 entry-point keys; no JSON load); 7ee178c7 (10-31 dup JSON keys, "
            "migrate keys, target shadow, codegen names); 6921e8a8 (11-19 `format` "
            "alias over an explicit null `fmt`; not a JSON key)"
        ),
        (
            "register, alias, or key two things under one name and check the second "
            "raises instead of replacing the first"
        ),
        (
            "duplicate keys in fetched JSON data keep the last value (workflow "
            "documents reject them); identical (name, value) entry-point pairs dedupe; "
            "a runtime `register` shadows an entry point, and `replace=True` is the "
            "explicit override; `CompositeStore` returns its first hit; a wired "
            "`in:count` on an operator (only processors reserve it)"
        ),
    ),
    "mixed-input": BugClass(
        (
            "47c409b5 (09-03 numeric strings); 9f1af91c (10-28 text-only XML root); "
            "682124d4 (10-28 DotDict non-str keys); 3a177544 (11-03 sort untyped "
            "values); e0f6e05b (11-03 empty CSV export); f82af774 (11-14 unindexable "
            "pairs); 4f642c6d (11-21 split count guard)"
        ),
        (
            "feed mixed-type, empty, and wrong-shape values to every sort, export, and "
            "pair input; each must give a defined result or a TypeError"
        ),
        (
            "a mixed str/int sort raising `TypeError`; DotDict `[]`/`in` one level "
            "past a scalar (pending its literal-access boundary); an unparseable date "
            "in an item's field fails a date rule silently (an out-of-range one warns)"
        ),
    ),
    "decode": BugClass(
        (
            "dc2d8917 (09-02 Reencoder read/readlines; no decode call); 4013ebf1 "
            "(10-04 text source splitting; no decode call); beee7028 (10-28 decoded "
            "reads after read(n); buffer state); 7ee178c7 (10-31 async_write "
            "multibyte, fetchtext BOM)"
        ),
        "split a multibyte character and a BOM across chunk boundaries",
        "`fetchtext` stripping a BOM by default (`strip_bom` opts out)",
    ),
    "stopiter": BugClass(
        (
            "654e3649 (09-30 splitter value peek); 4013ebf1 (10-04 empty source; no "
            "bare next); 7ee178c7 (10-31 empty CSV, regex zero-width, regex $N)"
        ),
        "feed an empty source and a zero-width match to every generator",
        _NONE_RECORDED,
    ),
    "frozen": BugClass(
        (
            "e937e766 (10-05 deep-frozen definitions); fe0ef32a (10-14 DotDict nested "
            "writes; not a record field); 1906d375 (10-21 definition snapshots; no "
            "frozen record pre-fix); 7ee178c7 (10-31 WriteCapabilities); 6dba2fe3 "
            "(11-17 Tee _Read; introduced in the same commit)"
        ),
        "mutate the list/dict/set a caller passed in and check the record is unchanged",
        "the shared `objconf`'s mutability (pending its configuration redesign)",
    ),
    "unbounded": BugClass(
        (
            "df5b36fd (10-29 fetch timeout); f3f371ad (10-29 async_map limit); "
            "7ee178c7 (10-31 async fetch timeout; not a default); c6a3838c (11-01 "
            "async cleanup under for; missing bound); 6dba2fe3 (11-17 branch lag; "
            "missing bound); 33c481e4 (11-19 splitter branches collected before the "
            "count check; missing bound)"
        ),
        "run each wait, read, and pool against a source that never answers",
        (
            "a `timeout(1)` mark replaced by an in-body `fail_after(1)` is not a "
            "dropped bound; a caller-supplied `0`/`inf` fetch timeout disables the "
            "bound by ruling"
        ),
    ),
    "equivalent-spellings": BugClass(
        (
            "cdbeda1a (10-31 port spellings); ededc9ce (11-03 regex field case); "
            "83630c28 (11-03 dotted/case rename fields); 9bbcf0ab (11-14 ModuleName "
            "resolvers); 466a3477 (11-23 split phrasal-verb ban); 33525cef (11-27 "
            "Decimal negative zero identity)"
        ),
        (
            "try a case variant, dotted form, zero-padded index, or NewType/str twin "
            "of every key lookup, group, or count, and check both spellings land on "
            "one entry"
        ),
        (
            "`.lower()` rather than `casefold` (it matches DotDict); numeric-string "
            "DotDict keys read as indexes (pending its literal-access boundary)"
        ),
    ),
    "failure-propagation": BugClass(
        (
            "64f59e8f (09-30 cleanup errors); c11c205d (10-27 dead worker process); "
            "9173167b (10-27 lone task failure); dd6867e8 (10-27 pickled errors); "
            "61aaa929 (11-21 failed close on a failed build); b2eceb31 (11-26 tee "
            "interrupted copy left the close failure off the interrupt); 53e28632 "
            "(11-27 failed run close left the run unfinished)"
        ),
        (
            "make a worker, task, or cleanup step die or raise, once and twice, and "
            "check the run raises the original error intact instead of hanging or "
            "replacing it"
        ),
        _NONE_RECORDED,
    ),
    "hash-order": BugClass(
        (
            "e937e766 (10-05 graph order); 7ee178c7 (10-31 tz abbreviations, hash "
            "module); 6395987b (11-04 docstring sections)"
        ),
        "rerun under two PYTHONHASHSEED values and diff the output order",
        "tz-abbreviation collisions resolved by sorted order (deterministic)",
    ),
    "option-forwarding": BugClass(
        (
            "274265b1 (10-21 run-pipe -t); e13819c4 (10-28 export writer/converter "
            "options); 516ee2ab (11-05 user agent over HTTP)"
        ),
        (
            "trace each caller-supplied option (keyword, flag, header, conf key) from "
            "the entry point to the call that consumes it and check it arrives "
            "unchanged and only there"
        ),
        (
            "unknown keywords on a direct module call reach the parser (they may be "
            "named inputs)"
        ),
    ),
    "bad-config": BugClass(
        (
            "fb7ea681 (10-29 out-of-range settings); 597a0181 (11-03 int cast "
            "overflow); cfbb627b (11-03 RIKO_ENCODING; not line-scannable); fcf97e1c "
            "(11-19 cast_datetime timestamp overflow; a named callee, not "
            "runtime-chosen)"
        ),
        (
            "set each RIKO_* variable and conf number to malformed, out-of-range, inf, "
            "and unknown values; each must warn and keep the default"
        ),
        (
            "a `try` that only builds a `Decimal` (construction never overflows); "
            "filter's `SWITCH` operations (comparisons never overflow)"
        ),
    ),
    "races": BugClass(
        (
            "cb586961 (11-03 racing plugin loads); acfd24be (11-03 nested node-thread "
            "waits); e01c4a58 (11-03 blocking cleanup bound)"
        ),
        (
            "run two loads/registers concurrently and check one instance is published; "
            "look for waits taken on a node thread"
        ),
        (
            "a `setdefault` publish whose racing factory may run twice (no lock held "
            "across imports); `temporary_registrations` not thread-safe, like "
            "`warnings.catch_warnings`"
        ),
    ),
    "timezones": BugClass(
        (
            "098f7aa8 (09-01 offset-aware utime); 3642b77f (09-03 tzinfo "
            "abbreviations); 7476dd9c (09-13 aware struct_times)"
        ),
        (
            "run each date conversion under two `TZ` values, across a DST change, and "
            "with an ambiguous abbreviation, and check the instant and zone name"
        ),
        _NONE_RECORDED,
    ),
    "packaging": BugClass(
        "6c6c6031 (09-12 missing async imports); e1e1ce0f (11-14 tzdata)",
        (
            "install without each optional extra and on a host with no system zone "
            "data, then import and run every module that needs it"
        ),
        _NONE_RECORDED,
    ),
    "serializer-framing": BugClass(
        (
            "4e4a8f1c (09-09 double headers); b347201e (11-14 JSONL newline); a6a9fd07 "
            "(11-27 export appended a second JSON document)"
        ),
        (
            "write zero, one, and several records in each format, appending too, and "
            "check headers, separators, and terminators appear once where required"
        ),
        "an empty csv/jsonl/json export writing its empty document",
    ),
    "colors": BugClass(
        (
            "6dba2fe3 (11-17 AsyncTee _advance/_close_source/_drop/_pull; introduced "
            "in the same commit)"
        ),
        "compare method names across each sync/async class pair",
        _NONE_RECORDED,
    ),
    "find-slice": BugClass(
        (
            "7ee178c7 (10-31 fetchpage.get_string); 6921e8a8 (11-19 legacy port "
            "suffix; removeprefix() not find())"
        ),
        (
            "search for an absent marker in every find()-then-slice path and every "
            "removeprefix()/removesuffix() whose result is read without a "
            "startswith()/endswith() check"
        ),
        _NONE_RECORDED,
    ),
    "kwarg-shadow": BugClass(
        (
            "a9079f9b (11-17 call keywords; a missing `/`); 322664c6 (11-19 "
            "prepare_call wrapper, _call_direct wrapper/items; a missing `/`)"
        ),
        (
            "pass a keyword named like each bound parameter through every `**kwargs` "
            "call path"
        ),
        (
            "a public first parameter passed twice (`pipe(items, item=x)`): Python's "
            "error is accurate and `item` is a reserved keyword"
        ),
    ),
    "inert-knob": BugClass(
        "466a3477 (11-22 C90 selected; mccabe table configured without its rule)",
        (
            "for each [tool.ruff.lint.<plugin>] table, confirm its rule prefix is "
            "selected; for each [tool.*] threshold, confirm the tool that reads it "
            "runs"
        ),
        (
            "a threshold read only by an explicit heavyweight check (pylint strict, "
            "pyright verify) that the standard lint suite leaves out"
        ),
    ),
    "other": BugClass(
        (
            "5196ad3a (09-09 default sink mode); ae33e7ba (09-09 FeedParserDict key "
            "remap); ff6a6030 (09-12 autorss Attributes guard); 8b95ee51 (10-28 "
            "http-prefixed file names); 186f976d (10-29 Context shipped to workers); "
            "bffd2dc0 (10-29 self-embedding workflow); 46d7c568 (10-31 half-applied "
            "register); 263fffe7 (11-03 registry-unaware metadata); 5f351de8 (11-19 "
            "subscripted generic alias inference); ee464524 (11-20 is_async_callable "
            "through partial)"
        ),
        (
            "no shared cause: reread the cited fix and its regression test when a "
            "change touches the same code"
        ),
        "a self-embedding stored workflow rejected statically, with no depth limit",
    ),
    "multi-return": BugClass(
        "house style: one return per function", "none (a style rule)", _NONE_RECORDED
    ),
}


class Lead(NamedTuple):
    path: Path
    line: int
    code: str
    kind: str
    message: str


def label(node: ast.AST) -> str:
    match node:
        case ast.Name(id=name):
            result = name
        case ast.Attribute(value=value, attr=attr):
            result = f"{label(value)}.{attr}"
        case ast.Call(func=func):
            result = f"{label(func)}()"
        case ast.Subscript(value=value):
            result = f"{label(value)}[]"
        case _:
            result = type(node).__name__

    return result


def is_value_like(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        last = label(node.func).split(".")[-1]
        result = last == "get" and bool(node.args)
    elif isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
        last = label(node).split(".")[-1].rstrip("[]")
        result = (
            not PREDICATE.search(last)
            and not BOOLISH.search(last)
            and not last.isupper()
            and bool(VALUE_NAME.search(last))
        )
    else:
        result = False

    return result


def is_set_expr(node: ast.AST) -> bool:
    match node:
        case ast.Set() | ast.SetComp():
            result = True
        case ast.Call(func=ast.Name(id="set" | "frozenset")):
            result = True
        case ast.Call(
            func=ast.Attribute(
                attr="difference" | "union" | "intersection" | "symmetric_difference"
            )
        ):
            result = True
        case ast.BinOp(op=op, left=left, right=right) if isinstance(op, SET_OPS):
            result = is_set_expr(left) or is_set_expr(right) or _is_keys(left)
        case _:
            result = False

    return result


def _is_keys(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and label(node.func).endswith(".keys")


def _annotation_names(node: ast.AST | None) -> set[str]:
    names = set()

    for sub in ast.walk(node) if node is not None else ():
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)

    return names


def _outer_annotation(node: ast.AST | None) -> str:
    match node:
        case ast.Subscript(value=value):
            result = label(value).split(".")[-1]
        case ast.Name() | ast.Attribute():
            result = label(node).split(".")[-1]
        case ast.BinOp(left=left):
            result = _outer_annotation(left)
        case _:
            result = ""

    return result


def _is_frozen_record(cls: ast.ClassDef) -> bool:
    result = False

    for dec in cls.decorator_list:
        name = label(dec.func if isinstance(dec, ast.Call) else dec)

        if name.split(".")[-1] == "frozen":
            result = True
        elif isinstance(dec, ast.Call) and name.split(".")[-1] in {
            "define",
            "dataclass",
            "attrs",
            "s",
        }:
            result = result or any(
                kw.arg == "frozen"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in dec.keywords
            )

    return result


def _calls_close(body: list[ast.stmt]) -> bool:
    return any(
        isinstance(n, ast.Attribute) and n.attr in {"close", "aclose"}
        for n in chain.from_iterable(map(ast.walk, body))
    )


def _is_narrowed(name: ast.Name) -> bool:
    node: ast.AST | None = name
    result = False

    while node is not None and not result:
        node = getattr(node, "_rm_parent", None)
        result = isinstance(node, ast.If) and any(
            isinstance(n, ast.Name) and n.id == name.id for n in ast.walk(node.test)
        )

    return result


def _field_has_converter(value: ast.AST | None) -> bool:
    return (
        isinstance(value, ast.Call)
        and label(value.func).split(".")[-1] in {"field", "ib", "attrib"}
        and any(kw.arg == "converter" for kw in value.keywords)
    )


def _is_in_test(node: ast.AST) -> bool:
    child, parent = node, getattr(node, "_rm_parent", None)

    while isinstance(parent, (ast.BoolOp, ast.UnaryOp)):
        child, parent = parent, getattr(parent, "_rm_parent", None)

    return (isinstance(parent, TEST_PARENTS) and parent.test is child) or (
        isinstance(parent, ast.comprehension) and child in parent.ifs
    )


def _is_lambda_param(node: ast.AST) -> bool:
    parent = getattr(node, "_rm_parent", None)

    while parent is not None and not isinstance(parent, ast.Lambda):
        parent = getattr(parent, "_rm_parent", None)

    return (
        isinstance(parent, ast.Lambda)
        and isinstance(node, ast.Name)
        and node.id in {a.arg for a in parent.args.args}
    )


def _is_reused_guard(node: ast.BoolOp) -> bool:
    first = node.values[0]
    text = ast.unparse(first)
    reused = isinstance(first, (ast.Name, ast.Attribute)) and any(
        ast.unparse(sub) == text
        for value in node.values[1:]
        for sub in ast.walk(value)
        if isinstance(sub, (ast.Name, ast.Attribute))
    )
    return reused and (is_value_like(first) or _is_lambda_param(first))


class Scanner(ast.NodeVisitor):
    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.lines = source.splitlines()
        self.leads: list[Lead] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.try_depth = 0
        self.aclosing_depth = 0
        self.tooling = "cli" in path.parts and "riko" in path.parts

    def add(self, node: ast.AST, code: str, kind: str, message: str) -> None:
        self.leads.append(
            Lead(self.path, getattr(node, "lineno", 0), code, kind, message)
        )

    @property
    def function(self) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return self.functions[-1] if self.functions else None

    def _is_generator(self, func: ast.AST | None) -> bool:
        return func is not None and any(
            isinstance(n, (ast.Yield, ast.YieldFrom))
            for n in ast.walk(func)
            if self._owner(n, func)
        )

    def _local_names(self, func: ast.AST | None) -> set[str]:
        """Gets the parameter and local names a function binds at runtime."""
        names: set[str] = set()

        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = func.args
            every = [*params.posonlyargs, *params.args, *params.kwonlyargs]
            every += [a for a in (params.vararg, params.kwarg) if a is not None]
            names = {a.arg for a in every}
            names |= {
                n.id
                for n in ast.walk(func)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
            }

        return names

    def _owner(self, node: ast.AST, func: ast.AST) -> bool:
        return getattr(node, "_rm_func", None) is func

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for sub in ast.walk(node):
            sub._rm_func = node  # type: ignore[attr-defined]

        for inner in ast.walk(node):
            if inner is not node and isinstance(
                inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                for sub in ast.walk(inner):
                    sub._rm_func = inner  # type: ignore[attr-defined]

        self._check_unbounded(node)
        self._check_find_slice(node)
        self.functions.append(node)
        self.generic_visit(node)
        self.functions.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        catches = any(
            h.type is None
            or "StopIteration" in label(h.type)
            or "Exception" in ast.unparse(h.type)
            for h in node.handlers
        )
        self.try_depth += catches
        local_names = self._local_names(self.function)
        dynamic = any(
            isinstance(sub.func, ast.Subscript)
            or (isinstance(sub.func, ast.Name) and sub.func.id in local_names)
            for stmt in node.body
            for sub in ast.walk(stmt)
            if isinstance(sub, ast.Call)
        )

        for handler in node.handlers:
            names = _annotation_names(handler.type)

            if (
                "ValueError" in names
                and not names & OVERFLOW_CATCHES
                and "InvalidOperation" in names
                and dynamic
            ):
                self.add(
                    handler,
                    "RM1101",
                    "bad-config",
                    "a decimal cast catches ValueError but not OverflowError; "
                    "int() of an infinite value escapes the default",
                )

        for stmt in node.body:
            self.visit(stmt)

        self.try_depth -= catches

        for part in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(part)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.visit_Try(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        wraps = any("aclosing" in label(item.context_expr) for item in node.items)
        self.aclosing_depth += wraps
        self.generic_visit(node)
        self.aclosing_depth -= wraps

    def visit_With(self, node: ast.With) -> None:
        wraps = any("closing" in label(item.context_expr) for item in node.items)
        self.aclosing_depth += wraps
        self.generic_visit(node)
        self.aclosing_depth -= wraps

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        parent = getattr(node, "_rm_parent", None)

        if (
            isinstance(node.op, ast.Or)
            and is_value_like(node.values[0])
            and ast.unparse(node.values[-1]) not in EMPTY_DEFAULTS
            and not self.tooling
            and not isinstance(
                parent,
                (ast.If, ast.While, ast.IfExp, ast.Assert, ast.UnaryOp, ast.BoolOp),
            )
        ):
            self.add(
                node,
                "RM101",
                "truthiness",
                f"`{label(node.values[0])} or ...` replaces a falsy value; "
                "test `is None`",
            )
        elif (
            isinstance(node.op, ast.And)
            and not self.tooling
            and not _is_in_test(node)
            and _is_reused_guard(node)
        ):
            self.add(
                node,
                "RM101",
                "truthiness",
                f"`{label(node.values[0])} and ...` returns a falsy value as is; "
                "test `is None`",
            )

        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if (
            isinstance(node.op, ast.Not)
            and is_value_like(node.operand)
            and not isinstance(node.operand, ast.Call)
            and not self.tooling
            and not _is_in_test(node)
        ):
            self.add(
                node,
                "RM102",
                "truthiness",
                f'`not {label(node.operand)}` in an expression; `0`/`""`/`False` '
                "may be valid",
            )

        self.generic_visit(node)

    def _check_test(self, node: ast.AST, test: ast.AST) -> None:
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            target = test.operand
        else:
            target = test

        if isinstance(target, ast.BoolOp):
            for value in target.values:
                self._check_test(node, value)
        elif (
            is_value_like(target)
            and not isinstance(target, ast.Call)
            and not self.tooling
        ):
            self.add(
                node,
                "RM102",
                "truthiness",
                f'truth test on `{label(target)}`; `0`/`""`/`False` may be valid',
            )

    def visit_If(self, node: ast.If | ast.While | ast.IfExp) -> None:
        self._check_test(node.test, node.test)
        test = node.test

        if (
            isinstance(node, ast.If)
            and isinstance(test, ast.Call)
            and label(test.func) == "isinstance"
            and len(test.args) == 2
            and _annotation_names(test.args[1]) & GENERATOR_TYPES
            and _calls_close(node.body)
            and not _calls_close(node.orelse)
        ):
            self.add(
                test,
                "RM401",
                "close",
                "only generators are closed; use get_sync_closer/get_async_closer",
            )

        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.visit_If(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit_If(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        for test in node.ifs:
            self._check_test(test, test)

        if is_set_expr(node.iter):
            self.add(
                node.iter,
                "RM201",
                "hash-order",
                "comprehension over a set; order varies with PYTHONHASHSEED",
            )

        self.generic_visit(node)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        if is_set_expr(node.iter):
            self.add(
                node,
                "RM201",
                "hash-order",
                "loop over a set; order varies with PYTHONHASHSEED",
            )

        if (
            isinstance(node, ast.AsyncFor)
            and isinstance(node.iter, ast.Call)
            and not self.aclosing_depth
            and isinstance(self.function, ast.AsyncFunctionDef)
            and self._is_generator(self.function)
        ):
            self.add(
                node,
                "RM403",
                "close",
                f"async generator iterates `{label(node.iter)}` without `aclosing`; "
                "abandoning it leaves the source open",
            )

        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = label(node.func)
        last = name.split(".")[-1].rstrip("()")

        if any(isinstance(a, ast.Starred) and is_set_expr(a.value) for a in node.args):
            self.add(
                node,
                "RM201",
                "hash-order",
                "set splatted into a call; argument order varies with PYTHONHASHSEED",
            )
        elif name == "hash" and (
            self.function is None or self.function.name != "__hash__"
        ):
            self.add(
                node,
                "RM201",
                "hash-order",
                "builtin hash() is seeded per process; use coercion._canonical.digest",
            )
        elif (
            name in {"list", "tuple", "sorted"}
            and node.args
            and is_set_expr(node.args[0])
            and name != "sorted"
        ):
            self.add(
                node,
                "RM201",
                "hash-order",
                f"{name}() of a set; order varies with PYTHONHASHSEED",
            )
        elif name.endswith(".join") and node.args and is_set_expr(node.args[0]):
            self.add(
                node,
                "RM201",
                "hash-order",
                "join over a set; order varies with PYTHONHASHSEED",
            )
        elif (
            name in {"json.load", "json.loads"}
            or (name in {"load", "loads"} and self._json_imported)
        ) and not any(kw.arg == "object_pairs_hook" for kw in node.keywords):
            self.add(
                node,
                "RM301",
                "last-wins",
                f"{name}() keeps the last of duplicate keys; pass object_pairs_hook",
            )
        elif (
            name == "bool"
            and len(node.args) == 1
            and is_value_like(node.args[0])
            and not isinstance(node.args[0], ast.Call)
            and not self.tooling
        ):
            self.add(
                node,
                "RM102",
                "truthiness",
                f'`bool({label(node.args[0])})`; `0`/`""`/`False` may be valid',
            )
        elif last in BOUNDED_ENV_READERS and not any(
            kw.arg == "minimum" for kw in node.keywords
        ):
            key = node.args[1] if len(node.args) > 1 else node
            self.add(
                key,
                "RM1102",
                "bad-config",
                f"`{last}` read has no `minimum=`; an out-of-range value is kept",
            )
        elif (
            name == "next"
            and len(node.args) == 1
            and not self.try_depth
            and self._is_generator(self.function)
        ):
            self.add(
                node,
                "RM103",
                "stopiter",
                "next() in a generator; StopIteration becomes RuntimeError "
                "(pass a default)",
            )
        elif (
            last == "decode"
            and isinstance(node.func, ast.Attribute)
            and CHUNK_NAME.search(label(node.func.value))
            and not any(kw.arg == "final" for kw in node.keywords)
        ):
            self.add(
                node,
                "RM501",
                "decode",
                f"`{label(node.func.value)}.decode()` per chunk splits multibyte "
                "characters; use getincrementaldecoder",
            )

        self.generic_visit(node)

    def _is_generic_param(self, node: ast.AST) -> bool:
        func = self.function
        result = False

        if func is not None and isinstance(node, ast.Name):
            args = func.args
            params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            annotation = next((a.annotation for a in params if a.arg == node.id), None)
            generic = GENERIC_ANNOTATIONS | {t.name for t in func.type_params}
            result = (
                annotation is not None
                and bool(_annotation_names(annotation) & generic)
                and not _is_narrowed(node)
            )

        return result

    def visit_Expr(self, node: ast.Expr) -> None:
        call = node.value

        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and CALLBACK_NAME.match(call.func.id)
        ):
            self.add(
                node,
                "RM402",
                "close",
                f"result of `{call.func.id}(...)` discarded; "
                "an awaitable return never runs",
            )
        elif (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "close"
            and not call.args
            and (
                (
                    isinstance(call.func.value, ast.Call)
                    and label(call.func.value.func).split(".")[-1] == "cast"
                )
                or self._is_generic_param(call.func.value)
            )
        ):
            self.add(
                node,
                "RM404",
                "close",
                f"`{label(call.func.value)}.close()` result discarded on a generic "
                "closable; an async close never runs (use resolve_closer)",
            )

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if _is_frozen_record(node) and not self.tooling:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    outer = _outer_annotation(stmt.annotation)
                    ann = ast.unparse(stmt.annotation)

                    if "ClassVar" in ann or _field_has_converter(stmt.value):
                        continue

                    if outer in MUTABLE_TYPES:
                        self.add(
                            stmt,
                            "RM701",
                            "frozen",
                            f"frozen field `{stmt.target.id}: {ann}` is mutable; "
                            "convert to a frozen type",
                        )
                    elif outer in {"frozenset", "tuple", "FrozenDict", "AbstractSet"}:
                        self.add(
                            stmt,
                            "RM701",
                            "frozen",
                            f"frozen field `{stmt.target.id}: {ann}` has no converter; "
                            "a caller's mutable value is kept",
                        )

        self.generic_visit(node)

    @property
    def _json_imported(self) -> bool:
        return any("from json import" in line for line in self.lines)

    def _check_unbounded(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        pairs = [
            *zip(
                positional[len(positional) - len(args.defaults) :],
                args.defaults,
                strict=True,
            ),
            *zip(args.kwonlyargs, args.kw_defaults, strict=True),
        ]

        for arg, default in pairs:
            if default is None or not re.search(r"(timeout|grace)$", arg.arg):
                continue

            text = ast.unparse(default)

            if text in {"0", "0.0", "inf", "math.inf", "float('inf')"}:
                self.add(
                    default,
                    "RM601",
                    "unbounded",
                    f"`{arg.arg}={text}` waits forever by default; default to settings",
                )

    def _check_find_slice(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        found: dict[str, ast.AST] = {}

        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Assign)
                and len(sub.targets) == 1
                and isinstance(sub.targets[0], ast.Name)
                and isinstance(sub.value, (ast.Call, ast.BinOp, ast.IfExp))
                and any(
                    isinstance(c, ast.Call)
                    and label(c.func).split(".")[-1].rstrip("()") in {"find", "rfind"}
                    for c in ast.walk(sub.value)
                )
            ):
                found[sub.targets[0].id] = sub

        checked = {
            n.id
            for cmp in ast.walk(node)
            if isinstance(cmp, ast.Compare)
            for n in ast.walk(cmp)
            if isinstance(n, ast.Name)
        }

        for sub in ast.walk(node):
            if isinstance(sub, ast.Slice):
                for name in {
                    n.id for n in ast.walk(sub) if isinstance(n, ast.Name)
                } & set(found) - checked:
                    self.add(
                        found[name],
                        "RM502",
                        "find-slice",
                        f"`{name}` from find() is sliced without a -1 check",
                    )
                    del found[name]


def _check_parity(tree: ast.Module, path: Path) -> Iterator[Lead]:
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)

    for name, sync in funcs.items():
        prefix = "_" if name.startswith("_") else ""
        twin = funcs.get(f"{prefix}a{name.removeprefix('_')}") or funcs.get(
            f"async_{name}"
        )

        if twin is None or isinstance(sync, ast.AsyncFunctionDef):
            continue

        def keywords(func: ast.AST) -> set[str]:
            return {
                kw.arg
                for call in ast.walk(func)
                if isinstance(call, ast.Call)
                for kw in call.keywords
                if kw.arg in IO_KEYWORDS
            }

        for missing, has, where in (
            (keywords(sync) - keywords(twin), name, twin),
            (keywords(twin) - keywords(sync), twin.name, sync),
        ):
            if missing:
                yield Lead(
                    path,
                    where.lineno,
                    "RM801",
                    "parity",
                    f"`{where.name}` never passes {sorted(missing)} "
                    f"that its twin `{has}` does",
                )


def _get_partial_bounds(tree: ast.Module) -> dict[str, int]:
    bounds: dict[str, int] = {}

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and label(node.func).split(".")[-1] in {"partial", "async_partial"}
            and node.args
            and not any(isinstance(a, ast.Starred) for a in node.args)
        ):
            target = label(node.args[0]).split(".")[-1]
            bounds[target] = max(bounds.get(target, 0), len(node.args) - 1)

    return bounds


def _check_kwarg_shadow(tree: ast.Module, path: Path) -> Iterator[Lead]:
    bounds = _get_partial_bounds(tree)
    methods = {
        id(func)
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef)
        for func in cls.body
    }

    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.args.kwarg is not None
            and bounds.get(node.name)
        ):
            params = [*node.args.posonlyargs, *node.args.args]
            receiver = bool(params) and params[0].arg in {"self", "cls"}
            skip = int(receiver and id(node) in methods)
            bound = params[skip : skip + bounds[node.name]]
            exposed = [a.arg for a in bound if a in node.args.args]

            if exposed:
                yield Lead(
                    path,
                    node.lineno,
                    "RM1001",
                    "kwarg-shadow",
                    f"`{node.name}` forwards **{node.args.kwarg.arg} but a partial "
                    f"binds {exposed} by position; a forwarded keyword of the same "
                    "name raises (make them positional-only)",
                )


def _get_methods(cls: ast.ClassDef) -> _Methods:
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    return {f.name: f for f in cls.body if isinstance(f, kinds)}


def _get_classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    classes: dict[str, ast.ClassDef] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.setdefault(node.name, node)

    return classes


@cache
def _index_classes(root: Path) -> dict[str, _Methods]:
    index: dict[str, _Methods] = {}

    for path in sorted((root / "riko").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError):
            continue

        for name, cls in _get_classes(tree).items():
            index.setdefault(name, _get_methods(cls))

    return index


def _check_colors(tree: ast.Module, path: Path) -> Iterator[Lead]:
    classes = _get_classes(tree)

    for name, cls in classes.items():
        base = name.removeprefix("Async")

        if base == name or not base:
            continue

        bases = {label(b).removesuffix("[]") for b in cls.bases}
        twins = [t for t in (base, f"Sync{base}") if t not in bases]
        local = [_get_methods(classes[t]) for t in twins if t in classes]
        index = _index_classes(ROOT)
        sync = (local or [index[t] for t in twins if t in index] or [{}])[0]

        for method, func in _get_methods(cls).items():
            if (
                isinstance(func, ast.AsyncFunctionDef)
                and isinstance(sync.get(method), ast.FunctionDef)
                and not method.startswith("__")
            ):
                yield Lead(
                    path,
                    func.lineno,
                    "RM802",
                    "colors",
                    f"async `{name}.{method}` shares its sync twin's plain "
                    "method name; prefix it `a`",
                )


def _gen_returns(node: ast.AST) -> Iterator[ast.Return]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Return):
            yield child
        elif not isinstance(child, SCOPE_NODES):
            yield from _gen_returns(child)


def _check_returns(tree: ast.Module, path: Path) -> Iterator[Lead]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            returns = list(_gen_returns(node))

            if len(returns) > 1:
                lines = ", ".join(str(r.lineno) for r in returns)

                for ret in returns:
                    yield Lead(
                        path,
                        ret.lineno,
                        "RM901",
                        "multi-return",
                        f"`{node.name}` returns at lines {lines}; "
                        "use one return at the end",
                    )


def _annotate_parents(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._rm_parent = node  # type: ignore[attr-defined]


def scan_file(path: Path) -> list[Lead]:
    source = path.read_text()
    tree = ast.parse(source)
    _annotate_parents(tree)
    scanner = Scanner(path, source)
    scanner.visit(tree)
    leads = [
        *scanner.leads,
        *_check_parity(tree, path),
        *_check_colors(tree, path),
        *_check_returns(tree, path),
        *_check_kwarg_shadow(tree, path),
    ]
    lines = scanner.lines
    kept = []

    for lead in sorted(set(leads), key=lambda x: (x.line, x.code)):
        text = lines[lead.line - 1] if 0 < lead.line <= len(lines) else ""
        suppressed = SUPPRESS.search(text)

        if suppressed is None or not any(
            lead.code.startswith(c.strip())
            for c in suppressed.group(1).split(",")
            if c.strip()
        ):
            kept.append(lead)

    return kept


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        [GIT, *args], cwd=ROOT, capture_output=True, text=True, check=check
    ).stdout


def changed_lines(diff: str) -> dict[Path, set[int]]:
    changed: dict[Path, set[int]] = {}
    current: Path | None = None
    number = 0

    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = None if line.endswith("/dev/null") else ROOT / line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match is not None else 0
        elif current is not None and number:
            if line.startswith("+"):
                changed.setdefault(current, set()).add(number)
                number += 1
            elif line.startswith(" "):
                number += 1

    return changed


def load_diff(diff_file: str) -> str:
    if diff_file == "-":
        text = sys.stdin.read()
        pointer = SAVED_DIFF.search(text)

        if pointer is not None and "diff --git" not in text:
            text = (ROOT / pointer.group(1)).read_text()
    else:
        text = Path(diff_file).read_text()

    return text


def resolve_scope(args: argparse.Namespace) -> dict[Path, set[int]] | None:
    if args.all:
        scope = None
    elif args.diff_file is not None:
        scope = changed_lines(load_diff(args.diff_file))
    elif args.staged:
        scope = changed_lines(git("diff", "--cached", "-U0"))
    else:
        diff = git("diff", "-U0", f"{args.since}...HEAD") if args.since else ""
        scope = changed_lines(diff + git("diff", "-U0", "HEAD"))

        for name in git("ls-files", "--others", "--exclude-standard").splitlines():
            scope[ROOT / name] = set(range(1, 1_000_000))

    return scope


def gen_files(args: argparse.Namespace) -> Iterator[Path]:
    roots = [Path(p).resolve() for p in args.paths] or [
        ROOT / "riko",
        *([ROOT / "tests"] if args.tests else []),
    ]

    for root in roots:
        for path in sorted(root.rglob("*.py")) if root.is_dir() else [root]:
            if (
                path.suffix == ".py"
                and path.name not in GENERATED
                and "__pycache__" not in path.parts
            ):
                yield path


def _get_rule_codes() -> dict[str, list[str]]:
    codes: dict[str, list[str]] = {}

    for code, kind in _RULE_ROW.findall(__doc__ or ""):
        codes.setdefault(kind, []).append(code)

    return codes


def gen_class_table() -> Iterator[str]:
    codes = _get_rule_codes()

    for kind, entry in sorted(CLASS_HISTORY.items(), key=lambda x: (-x[1].count, x[0])):
        rules = " ".join(codes.get(kind, [])) or "probe-only"
        yield f"## {kind}: {rules}; fixed {entry.count}x"
        yield f"refs: {entry.refs}"
        yield f"probe: {entry.probe}"
        yield f"safe: {entry.safe}\n"


def _quote(text: str) -> str:
    return f"'{text}'" if '"' in text else f'"{text}"'


def _gen_wrapped(text: str, width: int = 74) -> Iterator[str]:
    line = ""

    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word

        if len(candidate) + 1 > width and line:
            yield f"{line} "
            line = word
        else:
            line = candidate

    yield line


def _build_field(text: str) -> str:
    if text == _NONE_RECORDED:
        field = "        _NONE_RECORDED,"
    elif len(f"        {_quote(text)},") <= 88:
        field = f"        {_quote(text)},"
    else:
        body = "\n".join(f"            {_quote(c)}" for c in _gen_wrapped(text))
        field = f"        (\n{body}\n        ),"

    return field


def build_class_history_source(history: dict[str, BugClass] | None = None) -> str:
    lines = ["CLASS_HISTORY = {"]

    for name, entry in (CLASS_HISTORY if history is None else history).items():
        fields = [_build_field(text) for text in (entry.refs, entry.probe, entry.safe)]
        joined = ", ".join(f.strip().removesuffix(",") for f in fields)
        flat = all("\n" not in f for f in fields)

        if flat and len(head := f'    "{name}": BugClass({joined}),') <= 88:
            lines.append(head)
        elif flat and len(f"        {joined}") <= 88:
            lines += [f'    "{name}": BugClass(', f"        {joined}", "    ),"]
        else:
            lines += [f'    "{name}": BugClass(', *fields, "    ),"]

    return "\n".join([*lines, "}"])


def rewrap_class_history(path: Path = Path(__file__)) -> int:
    source = path.read_text()
    start = source.index("CLASS_HISTORY = {")
    end = source.index("\n}\n", start) + 2
    path.write_text(source[:start] + build_class_history_source() + source[end:])
    return 0


def _get_texts(
    history: dict[str, BugClass], non_behavioral: tuple[str, ...]
) -> list[str]:
    return [*(entry.refs for entry in history.values()), *non_behavioral]


def gen_unclassified(
    since: str | None = None, texts: list[str] | None = None
) -> Iterator[str]:
    base = since or git("describe", "--tags", "--abbrev=0").strip()
    texts = _get_texts(CLASS_HISTORY, NON_BEHAVIORAL) if texts is None else texts
    cited = set(chain.from_iterable(map(_SHA.findall, texts)))
    log = git("log", "--format=%h %s", f"{base}..HEAD", r"--grep=^\[FIX\]")

    for line in log.splitlines():
        sha = line.split(" ", 1)[0]

        if not any(sha.startswith(c) or c.startswith(sha) for c in cited):
            yield line


def report_unclassified(since: str | None = None) -> int:
    lines = list(gen_unclassified(since))

    for line in lines:
        print(line)

    return int(bool(lines))


def get_replay_status(sha: str) -> tuple[ReplayStatus, list[str]]:
    """
    Gets a fix's replay status from ``NON_BEHAVIORAL`` and ``CLASS_HISTORY``.

    Shas compare on their first 8 characters. The classes are every class citing the
    fix for ``probe-only``, the ruled ones for ``explained``, the ruled ones whose
    citing ref has no ``;`` note for ``unexplained``, and none otherwise.
    """
    short = sha[:8]
    codes = _get_rule_codes()
    notes = {
        kind: [
            ";" in group
            for cited, group in _CITED_GROUP.findall(entry.refs)
            if cited[:8] == short
        ]
        for kind, entry in CLASS_HISTORY.items()
    }
    cited = [kind for kind, groups in notes.items() if groups]
    ruled = [kind for kind in cited if kind in codes]
    bare = [kind for kind in ruled if not all(notes[kind])]

    if short in {entry[:8] for entry in NON_BEHAVIORAL}:
        status: tuple[ReplayStatus, list[str]] = ("non-behavioral", [])
    elif bare:
        status = ("unexplained", bare)
    elif ruled:
        status = ("explained", ruled)
    elif cited:
        status = ("probe-only", cited)
    else:
        status = ("uncited", [])

    return status


def report_status(shas: list[str]) -> int:
    for sha in shas:
        status, kinds = get_replay_status(sha)
        print(f"{sha} {status}: {', '.join(kinds)}" if kinds else f"{sha} {status}")

    return 0


def resolve_successor(sha: str) -> str | None:
    """
    Resolves a cited sha HEAD no longer reaches to its rewritten commit.

    The successor is the one commit since ``sha`` forked from HEAD with its subject,
    abbreviated to the cited length; none when no commit or several match.
    """
    subject = git("log", "-1", "--format=%s", sha, check=False).strip()
    base = git("merge-base", sha, "HEAD", check=False).strip()
    log = git("log", "--format=%H %s", f"{base}..HEAD") if subject and base else ""
    matches = [line[: len(sha)] for line in log.splitlines() if line[41:] == subject]
    return matches[0] if len(matches) == 1 else None


def _load_fix(sha: str) -> tuple[str, str]:
    day, _, patch = git("show", "--format=%ad", "--date=format:%m-%d", sha).partition(
        "\n"
    )
    return day, patch


def _place_uncommitted(match: re.Match[str], fixes: dict[str, tuple[str, str]]) -> str:
    _, day, note = match.groups()
    tokens = {
        token for groups in _NOTE_TOKEN.findall(note) for token in groups if token
    }
    scores = Counter(
        {
            sha: sum(bool(re.search(rf"\b{re.escape(t)}\b", patch)) for t in tokens)
            for sha, (fixed, patch) in fixes.items()
            if fixed == day
        }
    ).most_common(2)
    leads = (
        scores and scores[0][1] and (len(scores) == 1 or scores[1][1] < scores[0][1])
    )
    return f"{scores[0][0][:8]} {match.group(1)}" if leads else match.group()


def _replace_span(source: str, start: str, end: str, text: str) -> str:
    head = source.index(start)
    tail = source.index(end, head) + len(end)
    return source[:head] + text + source[tail:]


def remap_class_history(path: Path = Path(__file__), since: str | None = None) -> int:
    """
    Remaps this file's refs to the commits HEAD reaches after a rebase or fold.

    Rewrites ``CLASS_HISTORY`` (re-wrapped as ``--rewrap`` builds it) and
    ``NON_BEHAVIORAL`` in place, then prints each ref left unplaced and returns 1
    when any is.
    """
    reachable = git("rev-list", "HEAD").split()
    texts = _get_texts(CLASS_HISTORY, NON_BEHAVIORAL)
    cited = sorted(set(chain.from_iterable(map(_SHA.findall, texts))))
    stale = [sha for sha in cited if not any(h.startswith(sha) for h in reachable)]
    successors = {sha: s for sha in stale if (s := resolve_successor(sha)) is not None}

    def rename(match: re.Match[str]) -> str:
        return successors.get(match.group(), match.group())

    non_behavioral = tuple(successors.get(sha, sha) for sha in NON_BEHAVIORAL)
    renamed = {
        name: entry._replace(refs=_SHA.sub(rename, entry.refs))
        for name, entry in CLASS_HISTORY.items()
    }
    unclassified = gen_unclassified(since, _get_texts(renamed, non_behavioral))
    fixes = {
        line.split(" ", 1)[0]: _load_fix(line.split(" ", 1)[0]) for line in unclassified
    }
    history = {
        name: entry._replace(
            refs=_UNCOMMITTED.sub(lambda m: _place_uncommitted(m, fixes), entry.refs)
        )
        for name, entry in renamed.items()
    }
    source = _replace_span(
        path.read_text(),
        "CLASS_HISTORY = {",
        "\n}\n",
        f"{build_class_history_source(history)}\n",
    )
    source = _replace_span(
        source,
        "NON_BEHAVIORAL = (",
        "\n)\n",
        "\n".join(
            ["NON_BEHAVIORAL = (", *(f'    "{sha}",' for sha in non_behavioral), ")\n"]
        ),
    )
    path.write_text(source)
    unplaced = [
        *(
            f"{sha}: no single same-subject commit"
            for sha in stale
            if sha not in successors
        ),
        *(
            f"{name}: uncommitted {group}"
            for name, entry in history.items()
            for group, *_ in _UNCOMMITTED.findall(entry.refs)
        ),
    ]

    for line in unplaced:
        print(line)

    return int(bool(unplaced))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--staged", action="store_true")
    group.add_argument("--since")
    group.add_argument("--diff-file")
    parser.add_argument("--rule", action="append", default=[])
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--classes", action="store_true")
    parser.add_argument("--unclassified", action="store_true")
    parser.add_argument("--status", action="extend", nargs="+", default=[])
    parser.add_argument("--rewrap", action="store_true")
    parser.add_argument("--remap", action="store_true")
    args = parser.parse_args(argv)

    if args.classes:
        print("\n".join(gen_class_table()).rstrip())
        result = 0
    elif args.unclassified:
        result = report_unclassified(args.since)
    elif args.status:
        result = report_status(args.status)
    elif args.rewrap:
        result = rewrap_class_history()
    elif args.remap:
        result = remap_class_history(since=args.since)
    else:
        result = scan(args)

    return result


def scan(args: argparse.Namespace) -> int:
    scope = resolve_scope(args)
    found: list[tuple[Lead, str]] = []

    for path in gen_files(args):
        if scope is not None and path not in scope:
            continue

        lines = path.read_text().splitlines()

        for lead in scan_file(path):
            in_scope = scope is None or lead.line in scope[path]
            selected = not args.rule or any(lead.code.startswith(r) for r in args.rule)

            if in_scope and selected:
                found.append(
                    (lead, lines[lead.line - 1].strip()[:90] if lead.line else "")
                )

    def rank(entry: tuple[Lead, str]) -> tuple[int, str, str, int]:
        lead = entry[0]
        return (-CLASS_HISTORY[lead.kind].count, lead.code, str(lead.path), lead.line)

    counts = Counter(lead.kind for lead, _ in found)
    kind = None

    for lead, text in sorted(found, key=rank):
        if lead.kind != kind:
            kind = lead.kind
            entry = CLASS_HISTORY[kind]
            print(
                f"\n## {kind}: fixed {entry.count}x before ({entry.refs}); "
                f"{counts[kind]} leads"
            )

        inside = lead.path.is_relative_to(ROOT)
        where = lead.path.relative_to(ROOT) if inside else lead.path
        print(f"{where}:{lead.line}: {lead.code}: {lead.message} | {text}")

    print(
        f"\n{len(found)} leads "
        + " ".join(
            f"{k}={counts[k]}"
            for k in sorted(counts, key=lambda k: -CLASS_HISTORY[k].count)
        ),
        file=sys.stderr,
    )
    return int(bool(found))


if __name__ == "__main__":
    sys.exit(main())
