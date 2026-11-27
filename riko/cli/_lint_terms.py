# vim: sw=4:ts=4:expandtab
"""Checks shipped text for banned phrases, phase codes, and removed ext paths."""

from __future__ import annotations

import ast
import re
from itertools import chain
from typing import TYPE_CHECKING, NamedTuple

from riko.base._iterutils import gen_instances

from ._import_graph import load_ast
from ._shipped_text import gen_blocks, gen_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

_EXCLUDED_NAMES = frozenset({"MIGRATION.rst", "_lint_terms.py", "test_cli.py"})
_HISTORY_NAMES = frozenset({*_EXCLUDED_NAMES, "CHANGES.rst"})
_RESOLVER_CLASS = re.compile(r"(?:Test)?(\w*)Resolver")
_RESOLVER_STEMS = frozenset({"", "Workflow", "Pipeline"})


class BannedTerm(NamedTuple):
    """
    A phrase shipped text must not use, with the wording that replaces it.

    Attributes:

        phrase: The banned phrase (case-insensitive, whole words, optional plural, and
            matched across line breaks).

        instead: The replacement wording the reserved-terms rules give.

        split: Whether up to three words may sit between the phrase's words. E.g., for
            phrasal verbs like "tears the run down".

    """

    phrase: str
    instead: str
    split: bool = False


BANNED_TERMS: tuple[BannedTerm, ...] = (
    BannedTerm("execution context", "run environment (a `Context`)"),
    BannedTerm("shutdown budget", "shutdown timeout"),
    BannedTerm("coroutine function", "async function"),
    BannedTerm("sink pipe", "write module, or 'consumes the stream'"),
    BannedTerm("output module", "the `PipeDef` `output` node"),
    BannedTerm("cross-mode", "sync or async"),
    BannedTerm("host-mode", "sync or async"),
    BannedTerm("other mode", "sync or async"),
    BannedTerm("color", "sync or async"),
    BannedTerm("both sides", "sync and async"),
    BannedTerm("other side", "the sync or async counterpart"),
    BannedTerm("chosen side", "the sync or async run"),
    BannedTerm("each side", "sync and async"),
    BannedTerm("missing side", "the missing `pipe` or `async_pipe`"),
    BannedTerm("terminal sub-source", "secondary input stream"),
    BannedTerm("upstream stream", "input stream"),
    BannedTerm("upstreams", "input streams or node streams"),
    BannedTerm("downstreams", "output streams or downstream nodes"),
    BannedTerm("scoped run", "context manager (`pipeline.open(items)` returns one)"),
    BannedTerm("input requirements", "input schemas"),
    BannedTerm("input declaration", "an input's schema"),
    BannedTerm("keyword sink", "`**kwargs` or keyword arguments"),
    BannedTerm("bound keyword", "keyword argument"),
    BannedTerm("named workflow", "stored workflow"),
    BannedTerm("registered workflow", "stored workflow"),
    BannedTerm("imported workflow", "resolved workflow"),
    BannedTerm("sub-pipeline", "stored workflow"),
    BannedTerm("canonical workflow", "`Workflow`"),
    BannedTerm("authoring mapping", "`RawWorkflow`"),
    BannedTerm("canonical document", "workflow document"),
    BannedTerm("v2 document", "workflow document"),
    BannedTerm("pipeline JSON", "workflow document"),
    BannedTerm("DAG document", "serialized `PipeDag`"),
    BannedTerm("compiled pipeline", "workflow module"),
    BannedTerm("pipe file", "pipe script"),
    BannedTerm("wrapper options", "decoration options"),
    BannedTerm("decorator options", "decoration options"),
    BannedTerm("module wrapper", "pipe callable"),
    BannedTerm("decorated pipe", "pipe callable"),
    BannedTerm("sync interface", "a sync run, or `pipe`"),
    BannedTerm("async interface", "an async run, or `async_pipe`"),
    BannedTerm("async source", "async input stream or async iterable"),
    BannedTerm("call-time options", "call options or keyword arguments"),
    BannedTerm("export target", "export format"),
    BannedTerm("destination type", "cast type"),
    BannedTerm("item attribute", "item field"),
    BannedTerm("item's result", "a node's per-item results"),
    BannedTerm("resolver façade", "dispatcher"),
    BannedTerm("entry-point plugin", "plugin"),
    BannedTerm("extension package", "plugin"),
    BannedTerm("provider package", "plugin or integration"),
    BannedTerm("integration package", "plugin or integration"),
    BannedTerm("connector package", "plugin or integration"),
    BannedTerm("provider command", "backend command"),
    BannedTerm("teardown", "cleanup"),
    BannedTerm("tear down", "clean up or close", split=True),
    BannedTerm("tears down", "cleans up or closes", split=True),
    BannedTerm("torn down", "cleaned up or closed", split=True),
    BannedTerm("closeable", "closable"),
)


def _build_pattern(term: BannedTerm) -> re.Pattern[str]:
    """Compiles a phrase into a whole-word, case-insensitive pattern."""
    separator = r"\s+(?:\w+\s+){0,3}" if term.split else r"\s+"
    words = separator.join(re.escape(word) for word in term.phrase.split())
    return re.compile(rf"\b{words}s?\b", re.IGNORECASE)


_PHRASE_PATTERNS: tuple[tuple[BannedTerm, re.Pattern[str]], ...] = tuple(
    (term, _build_pattern(term)) for term in BANNED_TERMS
)

PHASE_CODE = BannedTerm("phase code", "a plain-English name for the pending work")

RUN_SCOPING = BannedTerm(
    "scoping a run", "context manager (`pipeline.open(items)` returns one)"
)

UPSTREAM_NOUN = BannedTerm("upstream as a noun", "input stream or node stream")
RETIRED_IS_ASYNC = BannedTerm("isasync", "is_async")
RETIRED_IS_SYNC = BannedTerm("issync", "is_sync")

REMOVED_EXT_PATH = BannedTerm(
    "removed riko.ext submodule path", "`riko.ext` or one of its submodules"
)

RETIRED_DESCRIBE = BannedTerm(
    "retired describe mode", "`describe_module`, or `input_schemas`/`dependencies`"
)

RESOLVER_CLASS = BannedTerm(
    "new *Resolver class",
    "a name for what the record holds ('resolver' means module-name lookup)",
)

_PATTERNS: tuple[tuple[BannedTerm, re.Pattern[str]], ...] = (
    *_PHRASE_PATTERNS,
    (PHASE_CODE, re.compile(r"\b[RP](?:1[0-2]|[0-9])[A-E]?(?:\.\d+)?\b")),
    (
        RUN_SCOPING,
        re.compile(
            r"\bscope[sd]?\s+(?:a|one|the|each)\s+run\b(?!')"
            r"|\bopen\b[^.]{0,40}?\bto\s+scope\b",
            re.IGNORECASE,
        ),
    ),
    (
        UPSTREAM_NOUN,
        re.compile(
            r"\b(?:its|their|the whole|a suspended)\s+(?:up|down)streams?\b"
            r"(?!\s+(?:nodes?|subgraph|reads?|reader)\b)",
            re.IGNORECASE,
        ),
    ),
)


_RETIRED_PATTERNS: tuple[tuple[BannedTerm, re.Pattern[str]], ...] = (
    (
        REMOVED_EXT_PATH,
        re.compile(r"\briko\.ext\.(?:config|decorators|names|protocols|registry)\b"),
    ),
    (RETIRED_DESCRIBE, re.compile(r"\bExecutionMode\b|\b(?i:describe[\s-]+modes?)\b")),
    (RETIRED_IS_ASYNC, re.compile(r"\bisasync\b")),
    (RETIRED_IS_SYNC, re.compile(r"\bissync\b")),
)


class TermIssue(NamedTuple):
    """
    One banned phrase found in shipped text.

    Attributes:

        path: The file containing the phrase.
        lineno: The line the phrase is on.
        found: The phrase as written.
        term: The banned term it matched.

    """

    path: Path
    lineno: int
    found: str
    term: BannedTerm

    def __str__(self) -> str:
        """Renders the issue as a ``path:line 'found' -> say 'instead'`` line."""
        found, instead = self.found, self.term.instead
        return f"{self.path}:{self.lineno} {found!r} -> say {instead!r}"


def _gen_pairs(
    block: str, *patterns: tuple[BannedTerm, re.Pattern[str]]
) -> Iterator[tuple[re.Match[str], BannedTerm]]:
    """Finds every ``patterns`` match in ``block`` with the term it matched."""
    for term, pattern in patterns:
        for match in pattern.finditer(block):
            yield match, term


def _gen_issues(
    patterns: tuple[tuple[BannedTerm, re.Pattern[str]], ...],
    *roots: Path,
    excluded: Iterable[str] = _EXCLUDED_NAMES,
) -> Iterator[TermIssue]:
    """Walks ``roots`` for every ``patterns`` match in their scannable files."""
    paths = chain.from_iterable(gen_files(root, *excluded) for root in roots)

    for path in paths:
        for start, block in gen_blocks(path):
            pairs = _gen_pairs(block, *patterns)

            for match, term in sorted(pairs, key=lambda pair: pair[0].start()):
                lineno = start + block.count("\n", 0, match.start())
                yield TermIssue(path, lineno, match.group(0), term)


def _gen_resolver_issues(*roots: Path) -> Iterator[TermIssue]:
    """Walks ``roots`` for classes named ``*Resolver`` beyond the reserved three."""
    paths = chain.from_iterable(gen_files(root, *_EXCLUDED_NAMES) for root in roots)

    for path in paths:
        if path.suffix == ".py":
            tree = load_ast(path)
            nodes = ast.walk(tree)
            classes = gen_instances(nodes, ast.ClassDef)

            for node in classes:
                match = _RESOLVER_CLASS.fullmatch(node.name)

                if match and match.group(1) not in _RESOLVER_STEMS:
                    yield TermIssue(path, node.lineno, node.name, RESOLVER_CLASS)


def gen_term_issues(*roots: Path) -> Iterator[TermIssue]:
    """
    Walks ``roots`` for banned phrases in Python strings/comments and prose files.

    Also tags classes named ``*Resolver`` other than ``Resolver``, ``WorkflowResolver``,
    and ``PipelineResolver`` (or their test classes).

    Args:

        roots: Files or directories to scan. Skips the migration guide because it quotes
            released wording. Skips the banned list and its tests because they spell out
            every phrase. The changelog may still name the removed ``riko.ext``
            submodules, the retired describe modes, and the old color-flag spellings
            since released entries keep the names they shipped with.

    Yields:

        One :class:`TermIssue` per match, in path then line order.

    """
    shipped = _gen_issues(_PATTERNS, *roots)
    retired = _gen_issues(_RETIRED_PATTERNS, *roots, excluded=_HISTORY_NAMES)
    resolvers = _gen_resolver_issues(*roots)
    issues = chain(shipped, retired, resolvers)
    yield from sorted(issues, key=lambda issue: issue[:2])


def gen_phrase_issues(*roots: Path) -> Iterator[TermIssue]:
    """
    Walks ``roots`` for banned phrases only, leaving phase codes and old paths alone.

    The internal docs cite phases and retired paths by design, so they are held to the
    reserved terms but not to the rules for shipped text.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`TermIssue` per match, in path then line order.

    """
    yield from _gen_issues(_PHRASE_PATTERNS, *roots)


__all__ = [
    "BANNED_TERMS",
    "PHASE_CODE",
    "REMOVED_EXT_PATH",
    "RESOLVER_CLASS",
    "RETIRED_DESCRIBE",
    "RUN_SCOPING",
    "UPSTREAM_NOUN",
    "BannedTerm",
    "TermIssue",
    "gen_phrase_issues",
    "gen_term_issues",
]
