# vim: sw=4:ts=4:expandtab

"""Documentation lint helpers for the manage CLI."""

import re
import tomllib
from collections import Counter
from collections.abc import Iterator
from glob import glob
from io import StringIO
from os.path import basename, dirname, exists, isdir, join
from pathlib import Path
from shutil import which
from subprocess import run
from typing import Any

from riko.base._paths import ROOT_DIR

from ._gen_api_surface import _BLOCK, _DOC, generate_api_surface

try:
    from docutils import nodes
    from docutils.core import publish_doctree
except ImportError:
    publish_doctree = None
    nodes = None

_TARGET_RE = re.compile(r"^\.\. _(?P<name>.+?): (?P<uri>\S.*)$", re.MULTILINE)
_LINE_ANCHOR_RE = re.compile(r"^L\d")
_DOCS_DIR = ROOT_DIR / "docs"
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
        "PHASE_CHECKLISTS.md",
        "ROADMAP.md",
        "RUNTIME_CONTRACT.md",
    }
)
_LEGACY_INSPIRATION = _INTERNAL_DOCS / "inspiration"
_API_SURFACE_GROUPS = frozenset(
    {
        "collections",
        "compile",
        "bado",
        "modules",
        "root-exceptions",
        "other",
        "extension",
    }
)
_GIT: str | None = which("git")

_STATUS_BANNER = re.compile(
    r"^\s*>?\s*\*\*status\b\s*(?::|\*\*)", re.IGNORECASE | re.MULTILINE
)
_SECTION_ROW = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)
_GAMEPLAN_LINK = re.compile(r"gameplans/([A-Za-z0-9._-]+\.md)")
_NON_AUTHORITATIVE_HEADER = re.compile(
    r"\b(retired|archived)\b|research/adr notebook|prior-art research|not as a task list",
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
_TARGET = re.compile(
    r"\b(target|targeted|planned|plan|next|prerequisite|prereq|future)\b", re.IGNORECASE
)


def _slugify(text: str) -> str:
    r"""
    Convert a heading to its GitHub anchor slug.

    TODO: Update meza and replace with
    slugify(text, allow_unicode=True, regex_pattern=r"[^\w-]+")
    """
    lowered = text.strip().lower()
    kept = "".join(c for c in lowered if c.isalnum() or c in {" ", "-", "_"})
    return kept.replace(" ", "-")


def _gen_doc_files(where: str | None) -> Iterator[str]:
    """Resolve the RST files to check."""
    for location in where.split(" ") if where else [ROOT_DIR, _DOCS_DIR]:
        if isdir(location):
            yield from glob(str(Path(location) / "*.rst"))
        elif Path(location).suffix == ".rst":
            yield str(location)


def _render_rst(path: str) -> tuple[str, Any]:
    """Read and parse an RST file into source text and doctree."""
    if not publish_doctree:
        raise RuntimeError("docutils not found")

    with open(path, encoding="utf-8") as f:
        text = f.read()

    overrides = {
        "report_level": 2,
        "halt_level": 5,
        "warning_stream": StringIO(),
        "input_encoding": "utf-8",
    }
    return text, publish_doctree(text, source_path=path, settings_overrides=overrides)


def _get_doc_anchors(doctree: Any) -> set[str]:
    """Compute the GitHub heading anchors a rendered document exposes."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()

    if nodes is None:
        raise RuntimeError("docutils not found")
    else:
        for node in doctree.findall(nodes.title):
            if isinstance(node.parent, (nodes.section, nodes.document)):
                base = _slugify(node.astext())
                count = seen.get(base, 0)
                anchors.add(base if count == 0 else f"{base}-{count}")
                seen[base] = count + 1

    return anchors


def _render_errors(path: str, doctree: Any) -> list[str]:
    """Collect docutils warning, error, and severe messages."""
    if nodes is None:
        raise RuntimeError("docutils not found")
    else:
        return [
            f"{path}:{node.get('line', '?')}: [{node['type']}] {node.children[0].astext()}"
            for node in doctree.findall(nodes.system_message)
            if node["level"] >= 2
        ]


def _get_path_anchors(path: str, cache: dict[str, set[str]]) -> set[str]:
    """Resolve cached anchors for a document, rendering it on first use."""
    if path not in cache:
        try:
            cache[path] = _get_doc_anchors(_render_rst(path)[1])
        except OSError:
            cache[path] = set()

    return cache[path]


def _check_links(path: str, text: str, cache: dict[str, set[str]]) -> list[str]:
    """Validate internal RST hyperlink targets resolve to files and anchors."""
    base_dir = dirname(path)
    errors: list[str] = []

    for match in _TARGET_RE.finditer(text):
        uri = match["uri"].strip()
        ref_path, _, anchor = uri.partition("#")
        target = join(base_dir, ref_path) if ref_path else path
        external = uri.startswith(("http://", "https://", "mailto:", "//"))

        if external:
            continue
        elif ref_path and not exists(target):
            errors.append(f"{path}: broken target '{uri}' (missing file)")
        elif anchor and not _LINE_ANCHOR_RE.match(anchor) and target.endswith(".rst"):
            where = ref_path or basename(path)

            if anchor not in _get_path_anchors(target, cache):
                errors.append(f"{path}: unknown anchor '#{anchor}' in {where}")

    return errors


def _check_rst(where: str | None = None) -> int:
    """Validate RST rendering and internal links."""
    if publish_doctree is None:
        raise RuntimeError("docutils not found")

    cache: dict[str, set[str]] = {}
    problems: list[str] = []

    for path in _gen_doc_files(where):
        text, doctree = _render_rst(path)
        cache[path] = _get_doc_anchors(doctree)
        problems.extend(_render_errors(path, doctree))
        problems.extend(_check_links(path, text, cache))

    for problem in problems:
        print(problem)

    return 1 if problems else 0


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


def _root_markdown_offenders() -> list[str]:
    """Find tracked root Markdown documents outside the authority allowlist."""
    tracked = _tracked_docs()
    return sorted(
        path.name
        for path in _INTERNAL_DOCS.glob("*.md")
        if path in tracked and path.name not in _ROOT_MARKDOWN
    )


def _version_tuple(text: str) -> tuple[int, int, int]:
    """Parse the first semantic version in text."""
    match = _VERSION.search(text)

    if match:
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
    return [
        path.name for path in _gameplan_paths() if _STATUS_BANNER.search(_read(path))
    ]


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


def _api_surface_offenders() -> list[str]:
    """Find API-surface blocks that drift from the contract declaration."""
    text = _read(_DOC)
    offenders: list[str] = []

    if not text:
        offenders.append("document is missing")
    else:
        present = {match["key"] for match in _BLOCK.finditer(text)}
        missing = sorted(_API_SURFACE_GROUPS - present)

        if missing:
            offenders.append(f"missing generated blocks: {missing}")

        if generate_api_surface(text) != text:
            offenders.append("generated blocks are stale; run `manage codegen --api`")

    return offenders


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


def _check_docs() -> int:
    """Validate static internal-document consistency and authority rules."""
    problems: list[str] = []
    roadmap = _read(_ROADMAP)
    counts = Counter(int(n) for n in _SECTION_ROW.findall(roadmap))
    expected = Counter(range(_EXPECTED_SECTIONS))

    if counts != expected:
        problems.append(
            f"{_ROADMAP}: section index must contain each §0-{_EXPECTED_SECTIONS - 1} once"
        )

    linked = set(_GAMEPLAN_LINK.findall(roadmap))
    gameplans = {path.name for path in _gameplan_paths()}
    missing = sorted(gameplans - linked)
    stale = sorted(linked - gameplans)

    if missing:
        problems.append(f"{_ROADMAP}: unindexed authoritative gameplans: {missing}")

    if stale:
        problems.append(f"{_ROADMAP}: links to missing gameplans: {stale}")

    if offenders := _root_markdown_offenders():
        problems.append(
            f"{_INTERNAL_DOCS}: root Markdown docs require explicit authority: {offenders}"
        )

    if _LEGACY_INSPIRATION.exists():
        problems.append(
            f"{_LEGACY_INSPIRATION}: prior-art material belongs under research/inspiration/"
        )

    if offenders := _authority_namespace_offenders():
        problems.append(
            f"{_GAMEPLANS}: archive/research material must leave gameplans/: {offenders}"
        )

    if offenders := _non_authoritative_listing_offenders(roadmap):
        problems.append(
            f"{_ROADMAP}: archive/research documents cannot appear in authority tables: "
            f"{offenders}"
        )

    if offenders := _status_banner_offenders():
        problems.append(
            f"{_GAMEPLANS}: status banners belong only in PHASE_CHECKLISTS.md: {offenders}"
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

    for problem in problems:
        print(problem)

    return 1 if problems else 0
