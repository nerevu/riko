# vim: sw=4:ts=4:expandtab

"""reStructuredText rendering and internal-link lint for the manage CLI."""

from __future__ import annotations

import re
from glob import glob
from io import StringIO
from os.path import basename, dirname, exists, isdir, join
from pathlib import Path
from typing import TYPE_CHECKING, Any

from riko.base._paths import DOCS_DIR, ROOT_DIR

try:
    from docutils import nodes
    from docutils.core import publish_doctree
except ImportError:
    publish_doctree = None
    nodes = None


if TYPE_CHECKING:
    from collections.abc import Iterator

_TARGET_RE = re.compile(r"^\.\. _(?P<name>.+?): (?P<uri>\S.*)$", re.MULTILINE)
_LINE_ANCHOR_RE = re.compile(r"^L\d")


def get_anchor(text: str) -> str:
    """Computes the GitHub anchor for a heading."""
    lowered = text.strip().lower()
    kept = "".join(c for c in lowered if c.isalnum() or c in {" ", "-", "_"})
    return kept.replace(" ", "-")


def _gen_doc_files(where: str | None) -> Iterator[str]:
    """Resolves the RST files to check."""
    for location in where.split(" ") if where else [ROOT_DIR, DOCS_DIR]:
        if isdir(location):
            yield from glob(str(Path(location) / "*.rst"))
        elif Path(location).suffix == ".rst":
            yield str(location)


def _render_rst(path: str) -> tuple[str, Any]:
    """Reads and parses an RST file into source text and doctree."""
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
    """Computes the GitHub heading anchors a rendered document exposes."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()

    if nodes is None:
        raise RuntimeError("docutils not found")
    else:
        for node in doctree.findall(nodes.title):
            if isinstance(node.parent, (nodes.section, nodes.document)):
                base = get_anchor(node.astext())
                count = seen.get(base, 0)
                anchors.add(base if count == 0 else f"{base}-{count}")
                seen[base] = count + 1

    return anchors


def _render_errors(path: str, doctree: Any) -> list[str]:
    """Collects docutils warning, error, and severe messages."""
    if nodes is None:
        raise RuntimeError("docutils not found")
    else:
        return [
            f"{path}:{node.get('line', '?')}: [{node['type']}] "
            f"{node.children[0].astext()}"
            for node in doctree.findall(nodes.system_message)
            if node["level"] >= 2
        ]


def _load_path_anchors(path: str, cache: dict[str, set[str]]) -> set[str]:
    """Loads a document's anchors, rendering and caching it on first use."""
    if path not in cache:
        try:
            cache[path] = _get_doc_anchors(_render_rst(path)[1])
        except OSError:
            cache[path] = set()

    return cache[path]


def _get_link_errors(path: str, text: str, cache: dict[str, set[str]]) -> list[str]:
    """Collects internal RST hyperlinks whose target file or anchor is missing."""
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

            if anchor not in _load_path_anchors(target, cache):
                errors.append(f"{path}: unknown anchor '#{anchor}' in {where}")

    return errors


def lint_rst(where: str | None = None) -> int:
    """Validates RST rendering and internal links."""
    if publish_doctree is None:
        raise RuntimeError("docutils not found")

    cache: dict[str, set[str]] = {}
    problems: list[str] = []

    for path in _gen_doc_files(where):
        text, doctree = _render_rst(path)
        cache[path] = _get_doc_anchors(doctree)
        problems.extend(_render_errors(path, doctree))
        problems.extend(_get_link_errors(path, text, cache))

    for problem in problems:
        print(problem)

    return 1 if problems else 0
