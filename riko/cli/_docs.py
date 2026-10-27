# vim: sw=4:ts=4:expandtab

"""Internal-documentation lint helpers for the manage CLI."""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from itertools import chain
from shutil import which
from subprocess import run
from typing import TYPE_CHECKING

from riko.base._paths import DOCS_DIR, PACKAGE_DIR, ROOT_DIR, TESTS_DIR

from ._gen_api_surface import _BLOCK, _DOC, generate_api_surface
from ._gen_verbs import VERB_BLOCKS, VERB_DOCS, VERB_PATTERNS, generate_verb_tables

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

_INTERNAL_DOCS = ROOT_DIR / "_docs"
_ROADMAP = _INTERNAL_DOCS / "ROADMAP.md"
_TRACKER = _INTERNAL_DOCS / "PHASE_CHECKLISTS.md"
_GAMEPLANS = _INTERNAL_DOCS / "gameplans"
_SEQUENCE = _GAMEPLANS / "implementation-sequence.md"
_PYPROJECT = ROOT_DIR / "pyproject.toml"
_EXPECTED_SECTIONS = 28
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
_LEGACY_INSPIRATION = _INTERNAL_DOCS / "inspiration"
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
_HISTORY_WORDS = re.compile(
    r"\b(?:deleted|retired|removed|dropped|merged|superseded)\b", re.IGNORECASE
)
_CITING_DOCS = (ROOT_DIR / "CONTRIBUTING.rst", ROOT_DIR / "CLAUDE.md")
_PATH_CITATION = re.compile(r"`(riko/[A-Za-z0-9_./-]+\.py)`")
_CURRENT_STATE_DOCS = (*_CITING_DOCS, ROOT_DIR / "README.rst")
_TARGET = re.compile(
    r"\b(target|targeted|planned|plan|next|prerequisite|prereq|future)\b", re.IGNORECASE
)


def _read(path: Path) -> str:
    """Read a UTF-8 document, returning empty text when it is absent."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _tracked_docs() -> set[Path]:
    """List internal Markdown documents tracked by git."""
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
    """List authoritative Markdown gameplans tracked by git in stable order."""
    tracked = _tracked_docs()
    globbed = _GAMEPLANS.glob("*.md") if _GAMEPLANS.exists() else []
    return sorted(path for path in globbed if path in tracked)


def _root_doc_paths() -> list[Path]:
    """List root internal Markdown documents tracked by git in stable order."""
    tracked = _tracked_docs()
    return sorted(path for path in _INTERNAL_DOCS.glob("*.md") if path in tracked)


def _root_markdown_offenders() -> list[str]:
    """Find tracked root Markdown documents outside the authority allowlist."""
    paths = _root_doc_paths()
    return [path.name for path in paths if path.name not in _ROOT_MARKDOWN]


def _version_tuple(text: str) -> tuple[int, int, int]:
    """Parse the first semantic version in text."""
    if match := _VERSION.search(text):
        major, minor, patch = match.groups()
        parsed = (int(major), int(minor), int(patch))
    else:
        parsed = (0, 0, 0)

    return parsed


def _packaged_version() -> tuple[int, int, int]:
    """Read the packaged project version from pyproject.toml."""
    data = tomllib.loads(_read(_PYPROJECT)) if _PYPROJECT.exists() else {}
    raw = data.get("project", {}).get("version", "0.0.0")
    return _version_tuple(raw)


def _status_banner_offenders() -> list[str]:
    """Find gameplans that claim phase status locally."""
    paths = _gameplan_paths()
    return [path.name for path in paths if _STATUS_BANNER.search(_read(path))]


def _authority_namespace_offenders() -> list[str]:
    """Find non-authoritative documents left in the active gameplan namespace."""
    offenders: list[str] = []

    for path in _gameplan_paths():
        header = "\n".join(_read(path).splitlines()[:8])

        if _NON_AUTHORITATIVE_HEADER.search(header):
            offenders.append(path.name)

    return offenders


def _non_authoritative_listing_offenders(roadmap: str) -> list[str]:
    """Find archive or research links listed in ROADMAP tables."""
    return [
        line.strip()
        for line in roadmap.splitlines()
        if line.lstrip().startswith("|") and _NON_AUTHORITATIVE_TABLE_LINK.search(line)
    ]


def _phase_closure_offenders() -> list[str]:
    """Find R-phases whose exit omits ordered ADD/MIGRATE/DELETE closure."""
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


def _gen_citation_offenders(
    scan: Callable[[str, Iterable[str]], Iterator[tuple[int, str]]],
    known: Iterable[str],
    *paths: Path,
) -> Iterator[str]:
    """Format each document's stale citations as ``path:line: cited`` offenders."""
    _known = frozenset(known)

    for path in paths:
        for lineno, cited in scan(_read(path), _known):
            yield f"{path.relative_to(ROOT_DIR)}:{lineno}: {cited}"


def _gen_stale_test_citation_offenders() -> Iterator[str]:
    """Find tracked docs citing test files that no longer exist."""
    known = (
        path.relative_to(ROOT_DIR).as_posix() for path in TESTS_DIR.glob("*/test_*.py")
    )
    docs = chain(
        _root_doc_paths(),
        _gameplan_paths(),
        _CITING_DOCS,
        sorted(DOCS_DIR.glob("*.rst")),
    )
    yield from _gen_citation_offenders(gen_stale_test_citations, known, *docs)


def _gen_stale_path_citation_offenders() -> Iterator[str]:
    """
    Find current-state docs citing source files that no longer exist.

    ``MILESTONES.md`` records history, so it is not scanned.
    """
    py_paths = PACKAGE_DIR.rglob("*.py")
    known = (path.relative_to(ROOT_DIR).as_posix() for path in py_paths)
    internal = (path for path in _root_doc_paths() if path.name != "MILESTONES.md")
    docs = chain(internal, _CURRENT_STATE_DOCS)
    yield from _gen_citation_offenders(gen_stale_path_citations, known, *docs)


def _api_surface_offenders() -> list[str]:
    """Find API-surface blocks that drift from the contract declaration."""
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
    """Find completion claims for versions newer than the packaged version."""
    return [
        line.strip()
        for path in (_TRACKER, _ROADMAP)
        for line in _read(path).splitlines()
        if _VERSION.search(line)
        and _version_tuple(line) > current
        and _COMPLETION.search(line)
        and not _TARGET.search(line)
    ]


def lint_docs() -> int:
    """Validates static internal-document consistency and authority rules."""
    problems: list[str] = []
    roadmap = _read(_ROADMAP)
    counts = Counter(int(n) for n in _SECTION_ROW.findall(roadmap))
    expected = Counter(range(_EXPECTED_SECTIONS))

    if counts != expected:
        problems.append(
            f"{_ROADMAP}: section index must contain each "
            f"§0-{_EXPECTED_SECTIONS - 1} once"
        )

    linked = set(_GAMEPLAN_LINK.findall(roadmap))
    gameplans = {path.name for path in _gameplan_paths()}

    if missing := sorted(gameplans - linked):
        problems.append(f"{_ROADMAP}: unindexed authoritative gameplans: {missing}")

    if stale := sorted(linked - gameplans):
        problems.append(f"{_ROADMAP}: links to missing gameplans: {stale}")

    if offenders := _root_markdown_offenders():
        problems.append(
            f"{_INTERNAL_DOCS}: root Markdown docs require explicit "
            f"authority: {offenders}"
        )

    if _LEGACY_INSPIRATION.exists():
        problems.append(
            f"{_LEGACY_INSPIRATION}: prior-art material belongs under "
            "research/inspiration/"
        )

    if offenders := _authority_namespace_offenders():
        problems.append(
            f"{_GAMEPLANS}: archive/research material must leave "
            f"gameplans/: {offenders}"
        )

    if offenders := _non_authoritative_listing_offenders(roadmap):
        problems.append(
            f"{_ROADMAP}: archive/research documents cannot appear in "
            f"authority tables: {offenders}"
        )

    if offenders := _status_banner_offenders():
        problems.append(
            f"{_GAMEPLANS}: status banners belong only in "
            f"PHASE_CHECKLISTS.md: {offenders}"
        )

    if offenders := _phase_closure_offenders():
        problems.append(
            f"{_SEQUENCE}: R-phase exits must contain ADD/MIGRATE/DELETE: {offenders}"
        )

    if offenders := _version_claim_offenders(_packaged_version()):
        problems.append(
            f"{_INTERNAL_DOCS}: completion claimed above packaged version: {offenders}"
        )

    if offenders := _api_surface_offenders():
        problems.append(f"{_DOC}: {'; '.join(offenders)}")

    if offenders := list(_gen_verb_table_offenders()):
        problems.append(f"verb tables drift: {'; '.join(offenders)}")

    if offenders := list(_gen_stale_test_citation_offenders()):
        problems.append(f"cited test files no longer exist: {'; '.join(offenders)}")

    if offenders := list(_gen_stale_path_citation_offenders()):
        problems.append(f"cited source files no longer exist: {'; '.join(offenders)}")

    for problem in problems:
        print(problem)

    return 1 if problems else 0
