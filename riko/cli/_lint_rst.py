# vim: sw=4:ts=4:expandtab

"""reStructuredText rendering and internal-link lint for the manage CLI."""

from __future__ import annotations

import re
from glob import glob
from io import StringIO
from os.path import basename, dirname, exists, isdir, join
from pathlib import Path
from subprocess import check_output
from typing import TYPE_CHECKING

from riko.base._paths import ARCHIVE_DIR, ROOT_DIR

try:
    from docutils import nodes
    from docutils.core import publish_doctree
except ImportError:
    publish_doctree = None
    nodes = None


if TYPE_CHECKING:
    from collections.abc import Iterator

    from docutils.nodes import document

_TARGET_RE = re.compile(r"^\.\. _(?P<name>.+?): (?P<uri>\S.*)$", re.MULTILINE)
_LINE_ANCHOR_RE = re.compile(r"^L\d")
_PYTHON_BLOCK_RE = re.compile(r"^(?P<indent>\s*)\.\. code-block:: python\s*$")
_NOTE_RE = re.compile(r"^\s*\.\. note::\s*$")
_PENDING_NOTE = "Pending."
_PROMPT = ">>>"
PLAIN_BLOCK_MESSAGE = (
    "Python code block without '>>>' prompts needs a leading '#' comment or an "
    f"adjacent '{_PENDING_NOTE}' note"
)


def _get_indent(line: str) -> int:
    """Gets the indentation width of a line."""
    return len(line) - len(line.lstrip())


def _get_block_end(lines: list[str], start: int, indent: int) -> int:
    """Gets the index just past the directive body that starts at ``start``."""
    end = start

    while end < len(lines) and (
        not lines[end].strip() or _get_indent(lines[end]) > indent
    ):
        end += 1

    return end


def _is_pending_note(lines: list[str], index: int) -> bool:
    """Checks whether the directive at ``index`` is a note that begins ``Pending.``."""
    content = next((line for line in lines[index + 1 :] if line.strip()), "")
    note_match = _NOTE_RE.match(lines[index])
    return bool(note_match) and content.strip().startswith(_PENDING_NOTE)


def _has_adjacent_pending_note(
    lines: list[str], start: int, end: int, indent: int
) -> bool:
    """Checks whether a ``Pending.`` note immediately precedes or follows a block."""
    before = start - 1

    while before >= 0 and (
        not lines[before].strip() or _get_indent(lines[before]) > indent
    ):
        before -= 1

    after = next((i for i in range(end, len(lines)) if lines[i].strip()), len(lines))
    preceded = before >= 0 and _is_pending_note(lines, before)
    followed = after < len(lines) and _is_pending_note(lines, after)
    return preceded or followed


def gen_plain_block_lines(text: str) -> Iterator[int]:
    """
    Finds the Python code blocks in ``text`` that neither run nor say why not.

    A ``.. code-block:: python`` without ``>>>`` prompts is never executed as a doctest,
    so it must mark itself as intentional: its first line is a ``#`` comment (naming the
    file it depicts or why it does not run), or a ``.. note::`` whose text begins
    ``Pending.`` sits immediately before or after it.

    Args:

        text: The RST source.

    Yields:

        int: The 1-based line number of each unmarked directive.

    Examples:

        >>> doctest = ".. code-block:: python\\n\\n    >>> 1 + 1\\n    2\\n"
        >>> list(gen_plain_block_lines(doctest))
        []
        >>> plain = ".. code-block:: python\\n\\n    x = 1\\n"
        >>> list(gen_plain_block_lines(plain))
        [1]

    """
    lines = text.splitlines()

    for index, line in enumerate(lines):
        if match := _PYTHON_BLOCK_RE.match(line):
            indent = len(match["indent"])
            end = _get_block_end(lines, index + 1, indent)
            block = lines[index + 1 : end]
            body = [stripped for raw in block if (stripped := raw.strip())]
            runs = any(stripped.startswith(_PROMPT) for stripped in body)
            commented = bool(body) and body[0].startswith("#")
            noted = _has_adjacent_pending_note(lines, index, end, indent)

            if not (runs or commented or noted):
                yield index + 1


def get_anchor(text: str) -> str:
    """Computes the GitHub anchor for a heading."""
    lowered = text.strip().lower()
    kept = "".join(c for c in lowered if c.isalnum() or c in {" ", "-", "_"})
    return kept.replace(" ", "-")


def _gen_tracked_docs() -> Iterator[str]:
    """Lists the tracked RST files outside the archived internal docs."""
    args = ["git", "ls-files", "*.rst"]

    for name in check_output(args, cwd=ROOT_DIR, text=True).splitlines():
        if not (path := ROOT_DIR / name).is_relative_to(ARCHIVE_DIR):
            yield str(path)


def _gen_doc_files(where: str | None) -> Iterator[str]:
    """Resolves the RST files to check."""
    if where:
        for location in where.split(" "):
            if isdir(location):
                yield from glob(str(Path(location) / "*.rst"))
            elif Path(location).suffix == ".rst":
                yield str(location)
    else:
        yield from _gen_tracked_docs()


def _render_rst(path: str) -> tuple[str, document]:
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


def _get_doc_anchors(doctree: document) -> set[str]:
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


def _render_errors(path: str, doctree: document) -> list[str]:
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
    """Validates RST rendering, internal links, and plain Python code-block markers."""
    if publish_doctree is None:
        raise RuntimeError("docutils not found")

    cache: dict[str, set[str]] = {}
    problems: list[str] = []

    for path in _gen_doc_files(where):
        text, doctree = _render_rst(path)
        cache[path] = _get_doc_anchors(doctree)
        problems.extend(_render_errors(path, doctree))
        problems.extend(_get_link_errors(path, text, cache))
        problems.extend(
            f"{path}:{lineno}: {PLAIN_BLOCK_MESSAGE}"
            for lineno in gen_plain_block_lines(text)
        )

    for problem in problems:
        print(problem)

    return 1 if problems else 0
