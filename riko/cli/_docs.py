# vim: sw=4:ts=4:expandtab

"""Internal-documentation lint helpers for the manage CLI."""

from __future__ import annotations

import ast
import re
import tomllib
from collections import Counter
from functools import partial
from itertools import chain
from shutil import which
from subprocess import run
from typing import TYPE_CHECKING

from riko.base._paths import DOCS_DIR, PACKAGE_DIR, PYPROJECT, ROOT_DIR, TESTS_DIR

from ._gen_api_surface import _BLOCK, _DOC, generate_api_surface
from ._gen_verbs import VERB_BLOCKS, VERB_DOCS, VERB_PATTERNS, generate_verb_tables
from ._import_graph import FUNCTION_NODES
from ._lint_terms import BANNED_TERMS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

    from ._lint_terms import BannedTerm

_INTERNAL_DOCS = ROOT_DIR / "_docs"
_STANDARD = _INTERNAL_DOCS / "DOCUMENTATION_STANDARD.md"

_RESERVED_TERMS = re.compile(
    r"^## Reserved terms$(.*?)(?=^## |\Z)", re.DOTALL | re.MULTILINE
)

_ROADMAP = _INTERNAL_DOCS / "ROADMAP.md"
_TRACKER = _INTERNAL_DOCS / "PHASE_CHECKLISTS.md"
_GAMEPLANS = _INTERNAL_DOCS / "gameplans"
_SEQUENCE = _GAMEPLANS / "implementation-sequence.md"
_EXPECTED_SECTIONS = 28

_SECTION_INDEX_RULE = (
    f"section index must contain each §0-{_EXPECTED_SECTIONS - 1} once"
)

_ROOT_MARKDOWN = frozenset(
    {
        "API_SURFACE.md",
        "DOCUMENTATION_STANDARD.md",
        "IMPLEMENTED.md",
        "INTERNALS.md",
        "KEY_PATHS.md",
        "MILESTONES.md",
        "ONBOARDING.md",
        "PHASE_CHECKLISTS.md",
        "ROADMAP.md",
        "RUNTIME_CONTRACT.md",
    }
)

_LEGACY_INSPIRATION = _INTERNAL_DOCS / "inspiration"
_INSPIRATION_RULE = "prior-art material belongs under research/inspiration/"

_API_SURFACE_GROUPS = frozenset(
    {"export", "compile", "bado", "modules", "root-exceptions", "other", "extension"}
)

_GIT: str | None = which("git")

_STATUS_BANNER = re.compile(
    r"^\s*>?\s*\*\*status\b\s*(?::|\*\*)", re.IGNORECASE | re.MULTILINE
)

_SECTION_ROW = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)
_GAMEPLAN_LINK = re.compile(r"gameplans/([A-Za-z0-9._-]+\.md)")

_NON_AUTHORITATIVE_HEADER = re.compile(
    r"\b(retired|archived)\b|research/adr notebook|prior-art research|"
    r"not as a task list",
    re.IGNORECASE,
)

_NON_AUTHORITATIVE_TABLE_LINK = re.compile(r"\]\((?:archive|research)/")

_R_PHASE = re.compile(
    r"^### (?P<phase>R\d+[A-Z]?)\s+—.*?(?=^### R\d+[A-Z]?\s+—|^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

_COMPLETION = re.compile(
    r"\b(complete|completed|delivered|shipped|landed|done)\b", re.IGNORECASE
)

_TEST_CITATION = re.compile(
    r"`((?:tests/)?(?:public|internal|functional)/test_\w+\.py)"
)

_SYMBOL_CITATION = re.compile(
    r"`(?:(?P<path>(?:tests/)?(?:public|internal|functional)/test_\w+\.py)::)?"
    r"(?P<cls>Test\w+)(?:::(?P<method>test_\w+))?"
)

_HISTORY_WORDS = re.compile(
    r"\b(?:deleted|retired|removed|dropped|merged|superseded)\b", re.IGNORECASE
)

_CITING_DOCS = (ROOT_DIR / "CONTRIBUTING.rst", ROOT_DIR / "CLAUDE.md")
_PATH_CITATION = re.compile(r"`(riko/[A-Za-z0-9_./-]+\.py)`")

_SOURCE_SYMBOL_CITATION = re.compile(
    r"(?:`(?P<first>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)(?=[`(\[])[^`]*`/)?"
    r"`(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)(?=[`(\[])[^`]*`"
    r" \(`(?P<path>riko/[A-Za-z0-9_./-]+\.py)`"
)

_CURRENT_STATE_DOCS = (*_CITING_DOCS, ROOT_DIR / "README.rst")
_TODO = re.compile(r"^\s*TODO\b")

_TARGET = re.compile(
    r"\b(target|targeted|planned|plan|next|prerequisite|prereq|future)\b", re.IGNORECASE
)


def _tracked_docs() -> set[Path]:
    """Lists internal Markdown documents tracked by git."""
    if not _GIT:
        raise RuntimeError("git not found")

    result = run(
        [_GIT, "ls-files", "*.md"],
        cwd=_INTERNAL_DOCS,
        capture_output=True,
        text=True,
        check=False,
    )
    return {_INTERNAL_DOCS / line for line in result.stdout.splitlines()}


def _gameplan_paths() -> list[Path]:
    """Lists authoritative Markdown gameplans tracked by git in stable order."""
    tracked = _tracked_docs()
    globbed = _GAMEPLANS.glob("*.md") if _GAMEPLANS.exists() else []
    return sorted(path for path in globbed if path in tracked)


def _non_authoritative_listing_offenders(roadmap: str) -> list[str]:
    """Finds archive or research links listed in ROADMAP tables."""
    return [
        line.strip()
        for line in roadmap.splitlines()
        if line.lstrip().startswith("|") and _NON_AUTHORITATIVE_TABLE_LINK.search(line)
    ]


def _section_index_offenders(roadmap: str) -> list[int]:
    """Finds section numbers the roadmap index lists other than exactly once."""
    counts = Counter(int(n) for n in _SECTION_ROW.findall(roadmap))
    expected = Counter(range(_EXPECTED_SECTIONS))
    return sorted((counts - expected) | (expected - counts))


def _unindexed_gameplan_offenders(roadmap: str) -> list[str]:
    """Finds authoritative gameplans the roadmap never links."""
    linked = set(_GAMEPLAN_LINK.findall(roadmap))
    return sorted({path.name for path in _gameplan_paths()} - linked)


def _missing_gameplan_offenders(roadmap: str) -> list[str]:
    """Finds roadmap gameplan links that name no tracked gameplan."""
    linked = set(_GAMEPLAN_LINK.findall(roadmap))
    return sorted(linked - {path.name for path in _gameplan_paths()})


_ROADMAP_CHECKS: dict[str, Callable[[str], Iterable[object]]] = {
    _SECTION_INDEX_RULE: _section_index_offenders,
    "unindexed authoritative gameplans": _unindexed_gameplan_offenders,
    "links to missing gameplans": _missing_gameplan_offenders,
    "archive/research documents cannot appear in authority tables": (
        _non_authoritative_listing_offenders
    ),
}

AS_BUILT_DOCS: tuple[Path, ...] = tuple(
    _INTERNAL_DOCS / name
    for name in (
        "IMPLEMENTED.md",
        "INTERNALS.md",
        "KEY_PATHS.md",
        "MILESTONES.md",
        "PHASE_CHECKLISTS.md",
        "ROADMAP.md",
    )
)

get_posix_root = lambda path: path.relative_to(ROOT_DIR).as_posix()


def _read(path: Path) -> str:
    """Reads a UTF-8 document, or empty text when it is absent."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _root_doc_paths() -> list[Path]:
    """Lists root internal Markdown documents tracked by git in stable order."""
    tracked = _tracked_docs()
    return sorted(path for path in _INTERNAL_DOCS.glob("*.md") if path in tracked)


def _root_markdown_offenders() -> list[str]:
    """Finds tracked root Markdown documents outside the authority allowlist."""
    paths = _root_doc_paths()
    return [path.name for path in paths if path.name not in _ROOT_MARKDOWN]


def _version_tuple(text: str) -> tuple[int, int, int]:
    """Parses the first semantic version in text."""
    if match := _VERSION.search(text):
        major, minor, patch = match.groups()
        parsed = (int(major), int(minor), int(patch))
    else:
        parsed = (0, 0, 0)

    return parsed


def _packaged_version() -> tuple[int, int, int]:
    """Reads the packaged project version from pyproject.toml."""
    data = tomllib.loads(_read(PYPROJECT)) if PYPROJECT.exists() else {}
    raw = data.get("project", {}).get("version", "0.0.0")
    return _version_tuple(raw)


def _status_banner_offenders() -> list[str]:
    """Finds gameplans that claim phase status locally."""
    paths = _gameplan_paths()
    return [path.name for path in paths if _STATUS_BANNER.search(_read(path))]


def _authority_namespace_offenders() -> list[str]:
    """Finds non-authoritative documents left in the active gameplan namespace."""
    offenders: list[str] = []

    for path in _gameplan_paths():
        header = "\n".join(_read(path).splitlines()[:8])

        if _NON_AUTHORITATIVE_HEADER.search(header):
            offenders.append(path.name)

    return offenders


def _phase_closure_offenders() -> list[str]:
    """Finds R-phases whose exit omits ordered ADD/MIGRATE/DELETE closure."""
    markers = ("- **ADD:**", "- **MIGRATE:**", "- **DELETE:**")
    offenders: list[str] = []

    for match in _R_PHASE.finditer(_read(_SEQUENCE)):
        phase = match.group("phase")
        body = match.group(0)
        exit_at = body.rfind("**Exit:**")
        closure = body[exit_at:] if exit_at >= 0 else ""
        positions = [closure.find(marker) for marker in markers]

        if (
            exit_at < 0
            or any(position < 0 for position in positions)
            or positions != sorted(positions)
        ):
            offenders.append(phase)

    return offenders


def gen_stale_test_citations(
    text: str, known: Iterable[str]
) -> Iterator[tuple[int, str]]:
    """
    Finds the test-file citations in ``text`` that name no current test file.

    A line that says the file was deleted, retired, removed, dropped, merged, or
    superseded records history, so its citations are not checked.

    Args:

        text: The document text.
        known: The current test files, as ``tests/<tier>/test_<name>.py`` paths.

    Yields:

        Each stale citation's line number and the path as cited.

    Examples:

        >>> from riko.cli._docs import gen_stale_test_citations
        >>>
        >>> known = ("tests/public/test_pipeline.py",)
        >>> text = "See `public/test_pipeline.py` and `public/test_gone.py`."
        >>> list(gen_stale_test_citations(text, known))
        [(1, 'public/test_gone.py')]
        >>> text = "`public/test_gone.py` was deleted."
        >>> list(gen_stale_test_citations(text, known))
        []

    """
    _known = frozenset(known)

    for lineno, line in enumerate(text.splitlines(), 1):
        if not _HISTORY_WORDS.search(line):
            for cited in _TEST_CITATION.findall(line):
                path = cited if cited.startswith("tests/") else f"tests/{cited}"

                if path not in _known:
                    yield (lineno, cited)


def gen_stale_test_symbol_citations(
    text: str, known: Iterable[str]
) -> Iterator[tuple[int, str]]:
    """
    Finds test-class and test-method citations in ``text`` that name nothing current.

    A citation is ``path::Class``, ``path::Class::test``, or ``Class::test``, where
    ``path`` is a ``tests/<tier>/test_<name>.py`` file (the ``tests/`` prefix may be
    omitted). A citation whose file is missing is left to the test-file check, and a
    line that records history (deleted, retired, removed, dropped, merged,
    superseded) is not checked.

    Args:

        text: The document text.
        known: The current symbols, each as ``tests/<tier>/test_x.py::Class``,
            ``tests/<tier>/test_x.py::Class::test``, or ``Class::test``, plus the
            current test files as plain paths.

    Yields:

        Each stale citation's line number and the citation as written.

    Examples:

        >>> from riko.cli._docs import gen_stale_test_symbol_citations
        >>>
        >>> path = "tests/public/test_pipeline.py"
        >>> known = (path, f"{path}::TestClose", "TestClose::test_twice")
        >>> text = "`public/test_pipeline.py::TestClose` and `TestClose::test_once`"
        >>> list(gen_stale_test_symbol_citations(text, known))
        [(1, 'TestClose::test_once')]
        >>> text = "`public/test_pipeline.py::TestGone` was removed."
        >>> list(gen_stale_test_symbol_citations(text, known))
        []

    """
    _known = frozenset(known)

    for lineno, line in enumerate(text.splitlines(), 1):
        if _HISTORY_WORDS.search(line):
            continue

        for match in _SYMBOL_CITATION.finditer(line):
            cited, method = match["path"], match["method"]
            path = None if cited is None else f"tests/{cited.removeprefix('tests/')}"
            symbol = match["cls"] if method is None else f"{match['cls']}::{method}"
            key = symbol if path is None else f"{path}::{symbol}"
            checked = method is not None or path is not None
            present = path is None or path in _known

            if checked and present and key not in _known:
                yield (lineno, match[0].lstrip("`"))


def gen_test_symbols(*paths: Path) -> Iterator[str]:
    """
    Walks test files for the citable symbols ``gen_stale_test_symbol_citations`` reads.

    Args:

        paths: The test files to index.

    Yields:

        Each file's path, then ``path::Class``, ``path::Class::test``, and
        ``Class::test`` for every top-level ``Test<Subject>`` class and its tests.

    """
    for path in paths:
        rel = get_posix_root(path)
        yield rel
        tree = ast.parse(_read(path))

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                yield f"{rel}::{node.name}"

                for member in node.body:
                    is_func = isinstance(member, FUNCTION_NODES)

                    if is_func and member.name.startswith("test"):
                        yield f"{rel}::{node.name}::{member.name}"
                        yield f"{node.name}::{member.name}"


def gen_stale_path_citations(
    text: str, known: Iterable[str]
) -> Iterator[tuple[int, str]]:
    """
    Finds backticked ``riko/*.py`` citations that name no current source file.

    A line that says the file was deleted, retired, removed, dropped, merged, or
    superseded records history, so its citations are not checked.

    Args:

        text: The document text.
        known: The current source files, as ``riko/...py`` paths.

    Yields:

        Each stale citation's line number and cited path.

    Examples:

        >>> from riko.cli._docs import gen_stale_path_citations
        >>>
        >>> known = ("riko/runtime/_export.py",)
        >>> text = "See `riko/runtime/_export.py` and `riko/runtime/collections.py`."
        >>> list(gen_stale_path_citations(text, known))
        [(1, 'riko/runtime/collections.py')]
        >>> list(gen_stale_path_citations("`riko/old.py` was deleted.", known))
        []

    """
    _known = frozenset(known)

    for lineno, line in enumerate(text.splitlines(), 1):
        if not _HISTORY_WORDS.search(line):
            for cited in _PATH_CITATION.findall(line):
                if cited not in _known:
                    yield (lineno, cited)


def gen_stale_source_symbol_citations(
    text: str, known: Iterable[str]
) -> Iterator[tuple[int, str]]:
    """
    Finds ``name`` (``riko/...py``) citations whose file no longer binds the name.

    The name is an identifier or ``Class.member``, optionally followed by a call or
    subscript (``name(...)``, ``Name[T]``). A ``first``/``name`` pair checks both, and
    a bare ``name`` after a dotted ``first`` takes its class (``C.x()``/``y()`` cites
    ``C.y``). A citation whose file is missing is left to the source-file check. A line
    that records history (deleted, retired, removed, dropped, merged, superseded) is not
    checked.

    Args:

        text: The document text.
        known: The current source files as ``riko/...py`` paths, plus their symbols
            as ``path::name`` and ``path::Class.member``.

    Yields:

        Each stale citation's line number and the citation as ``path::name``.

    Examples:

        >>> from riko.cli._docs import gen_stale_source_symbol_citations
        >>>
        >>> path = "riko/runtime/_export.py"
        >>> known = (path, f"{path}::export", f"{path}::Formats.JSON")
        >>> text = f"`export(...)` (`{path}`) and `list_formats` (`{path}`)"
        >>> list(gen_stale_source_symbol_citations(text, known))
        [(1, 'riko/runtime/_export.py::list_formats')]
        >>> text = f"`Formats.CSV`/`JSON` (`{path}`) and `gone`/`export` (`{path}`)"
        >>> for _, key in gen_stale_source_symbol_citations(text, known):
        ...     print(key)
        riko/runtime/_export.py::Formats.CSV
        riko/runtime/_export.py::gone
        >>> text = f"`Formats.CSV` (`{path}`) was removed."
        >>> list(gen_stale_source_symbol_citations(text, known))
        []

    """
    _known = frozenset(known)

    for lineno, line in enumerate(text.splitlines(), 1):
        if not _HISTORY_WORDS.search(line):
            for match in _SOURCE_SYMBOL_CITATION.finditer(line):
                path, first, name = match["path"], match["first"], match["name"]

                if first is not None and "." in first and "." not in name:
                    name = f"{first.rpartition('.')[0]}.{name}"

                for cited in (first, name):
                    key = f"{path}::{cited}"

                    if cited is not None and path in _known and key not in _known:
                        yield (lineno, key)


def _gen_bound_names(*body: ast.stmt) -> Iterator[tuple[str, ast.stmt]]:
    """Walks a scope's statements, into conditional blocks, for the names bound."""
    for node in body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                yield (node.name, node)
            case ast.Assign(targets=targets):
                for target in targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name):
                            yield (name.id, node)
            case (
                ast.AnnAssign(target=ast.Name(id=name))
                | ast.TypeAlias(name=ast.Name(id=name))
            ):
                yield (name, node)
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                for alias in aliases:
                    yield (alias.asname or alias.name.partition(".")[0], node)
            case ast.If() | ast.Try() | ast.With():
                handlers = getattr(node, "handlers", ())
                nested = (*node.body, *getattr(node, "orelse", ()))
                final = (*getattr(node, "finalbody", ()),)
                handled = (stmt for handler in handlers for stmt in handler.body)
                yield from _gen_bound_names(*nested, *handled, *final)


def gen_source_symbols(*paths: Path) -> Iterator[str]:
    """
    Walks source files for the symbols ``gen_stale_source_symbol_citations`` reads.

    Args:

        paths: The source files to index.

    Yields:

        Each file's path, then ``path::name`` for every name the module binds at top
        level (imports included) and ``path::Class.member`` for every name a top-level
        class binds.

    """
    for path in paths:
        rel = get_posix_root(path)
        yield rel

        for name, node in _gen_bound_names(*ast.parse(_read(path)).body):
            yield f"{rel}::{name}"

            if isinstance(node, ast.ClassDef):
                for member, _ in _gen_bound_names(*node.body):
                    yield f"{rel}::{name}.{member}"


def gen_todo_lines(text: str) -> Iterator[int]:
    """
    Finds lines that start with a ``TODO`` marker.

    Args:

        text: The document text.

    Yields:

        Each marker's line number.

    Examples:

        >>> from riko.cli._docs import gen_todo_lines
        >>>
        >>> text = "Intro.\\n\\nTODO: add seeding\\nA mid-line TODO is fine"
        >>> list(gen_todo_lines(text))
        [3]

    """
    for lineno, line in enumerate(text.splitlines(), 1):
        if _TODO.match(line):
            yield lineno


def gen_unruled_terms(text: str, *terms: BannedTerm) -> Iterator[str]:
    """
    Finds banned phrases the reserved-terms section gives no ruling for.

    Args:

        text: The documentation standard's Markdown text.

        terms: The banned terms each needing a ruling.

    Yields:

        Each banned phrase missing from the ``## Reserved terms`` section, which ends at
        the next level-two heading; a missing section rules on nothing.

    Example:

        >>> from riko.cli._lint_terms import BannedTerm
        >>> text = "## Reserved terms\\nNot `Fast Lane`.\\n## Voice\\nslow lane\\n"
        >>> terms = (BannedTerm("fast lane", "run"), BannedTerm("slow lane", "run"))
        >>> list(gen_unruled_terms(text, *terms))
        ['slow lane']

    """
    match = _RESERVED_TERMS.search(text)
    section = "" if match is None else match[1].lower()
    yield from (term.phrase for term in terms if term.phrase.lower() not in section)


def _gen_unruled_term_offenders() -> Iterator[str]:
    """Finds banned phrases the tracked documentation standard gives no ruling for."""
    yield from gen_unruled_terms(_read(_STANDARD), *BANNED_TERMS)


def _gen_todo_offenders() -> Iterator[str]:
    """Names each ``TODO`` line left in the shipped user docs."""
    docs = (ROOT_DIR / "README.rst", ROOT_DIR / "CONTRIBUTING.rst")

    for path in (*docs, *sorted(DOCS_DIR.glob("*.rst"))):
        for lineno in gen_todo_lines(_read(path)):
            yield f"{get_posix_root(path)}:{lineno}"


def _gen_citation_offenders(
    scan: Callable[[str, Iterable[str]], Iterator[tuple[int, str]]],
    known: Iterable[str],
    *paths: Path,
) -> Iterator[str]:
    """Formats each document's stale citations as ``path:line: cited`` offenders."""
    _known = frozenset(known)

    for path in paths:
        for lineno, cited in scan(_read(path), _known):
            yield f"{get_posix_root(path)}:{lineno}: {cited}"


def _gen_test_citing_doc_paths() -> Iterator[Path]:
    """Finds the tracked docs whose test-file and test-symbol citations are checked."""
    yield from chain(
        _root_doc_paths(),
        _gameplan_paths(),
        _CITING_DOCS,
        sorted(DOCS_DIR.glob("*.rst")),
    )


def _gen_stale_test_citation_offenders() -> Iterator[str]:
    """Finds tracked docs citing test files that no longer exist."""
    known = map(get_posix_root, TESTS_DIR.glob("*/test_*.py"))
    docs = _gen_test_citing_doc_paths()
    yield from _gen_citation_offenders(gen_stale_test_citations, known, *docs)


def _gen_stale_test_symbol_offenders() -> Iterator[str]:
    """Finds tracked docs citing test classes or tests that no longer exist."""
    known = gen_test_symbols(*sorted(TESTS_DIR.glob("*/test_*.py")))
    docs = _gen_test_citing_doc_paths()
    yield from _gen_citation_offenders(gen_stale_test_symbol_citations, known, *docs)


def _gen_stale_path_citation_offenders() -> Iterator[str]:
    """
    Finds current-state docs citing source files that no longer exist.

    ``MILESTONES.md`` records history, so it is not scanned.
    """
    py_paths = PACKAGE_DIR.rglob("*.py")
    known = map(get_posix_root, py_paths)
    internal = (path for path in _root_doc_paths() if path.name != "MILESTONES.md")
    docs = chain(internal, _CURRENT_STATE_DOCS)
    yield from _gen_citation_offenders(gen_stale_path_citations, known, *docs)


def _gen_stale_source_symbol_offenders() -> Iterator[str]:
    """Finds current-state docs citing names their cited source file no longer binds."""
    known = gen_source_symbols(*sorted(PACKAGE_DIR.rglob("*.py")))
    internal = (path for path in _root_doc_paths() if path.name != "MILESTONES.md")
    docs = chain(internal, _CURRENT_STATE_DOCS)
    yield from _gen_citation_offenders(gen_stale_source_symbol_citations, known, *docs)


def _api_surface_offenders() -> list[str]:
    """Finds API-surface blocks that drift from the contract declaration."""
    offenders: list[str] = []

    if text := _read(_DOC):
        present = {match["key"] for match in _BLOCK.finditer(text)}

        if missing := sorted(_API_SURFACE_GROUPS - present):
            offenders.append(f"missing generated blocks: {missing}")

        if generate_api_surface(text) != text:
            offenders.append("generated blocks are stale; run `manage codegen --api`")
    else:
        offenders.append("document is missing")

    return offenders


def _gen_verb_table_offenders() -> Iterator[str]:
    """Finds verb tables that drift from the verb declaration."""
    for path, fmt in VERB_DOCS.items():
        text = _read(path)
        present = {match["key"] for match in VERB_PATTERNS[fmt].finditer(text)}

        if missing := sorted(VERB_BLOCKS - present):
            yield f"{path.name}: missing verb tables {missing}"
        elif generate_verb_tables(text, fmt) != text:
            yield f"{path.name}: verb tables are stale; run `manage codegen --verbs`"


def _version_claim_offenders(current: tuple[int, int, int]) -> list[str]:
    """Finds completion claims for versions newer than the packaged version."""
    return [
        line.strip()
        for path in (_TRACKER, _ROADMAP)
        for line in _read(path).splitlines()
        if _VERSION.search(line)
        and _version_tuple(line) > current
        and _COMPLETION.search(line)
        and not _TARGET.search(line)
    ]


def _legacy_inspiration_offenders() -> list[str]:
    """Finds the retired prior-art folder when it still exists."""
    return [_LEGACY_INSPIRATION.name] if _LEGACY_INSPIRATION.exists() else []


def lint_docs() -> int:
    """Validates static internal-document consistency and authority rules."""
    roadmap = _read(_ROADMAP)
    roadmap_items = _ROADMAP_CHECKS.items()
    roadmap_checks = {
        f"{_ROADMAP}: {rule}": partial(check, roadmap) for rule, check in roadmap_items
    }
    checks: dict[str, Callable[[], Iterable[object]]] = {
        **roadmap_checks,
        f"{_INTERNAL_DOCS}: root Markdown docs require explicit authority": (
            _root_markdown_offenders
        ),
        f"{_LEGACY_INSPIRATION}: {_INSPIRATION_RULE}": _legacy_inspiration_offenders,
        f"{_GAMEPLANS}: archive/research material must leave gameplans/": (
            _authority_namespace_offenders
        ),
        f"{_GAMEPLANS}: status banners belong only in PHASE_CHECKLISTS.md": (
            _status_banner_offenders
        ),
        f"{_SEQUENCE}: R-phase exits must contain ADD/MIGRATE/DELETE": (
            _phase_closure_offenders
        ),
        f"{_INTERNAL_DOCS}: completion claimed above packaged version": partial(
            _version_claim_offenders, _packaged_version()
        ),
        str(_DOC): _api_surface_offenders,
        "verb tables drift": _gen_verb_table_offenders,
        "cited test files no longer exist": _gen_stale_test_citation_offenders,
        "cited tests no longer exist": _gen_stale_test_symbol_offenders,
        "cited source files no longer exist": _gen_stale_path_citation_offenders,
        "cited source names no longer exist": _gen_stale_source_symbol_offenders,
        f"{_STANDARD}: banned phrases without a reserved-terms ruling": (
            _gen_unruled_term_offenders
        ),
        "user docs carry TODO lines": _gen_todo_offenders,
    }
    problems = [
        f"{label}: {'; '.join(map(str, found))}"
        for label, check in checks.items()
        if (found := list(check()))
    ]

    for problem in problems:
        print(problem)

    return 1 if problems else 0
