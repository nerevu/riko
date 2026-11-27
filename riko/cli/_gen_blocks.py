# vim: sw=4:ts=4:expandtab
"""
Generates marked blocks inside hand-written documents and checks them for drift.

A marked block sits between a begin marker naming its key and an end marker. In
Markdown the markers are ``<!-- key -->`` and ``<!-- /key -->``; in reStructuredText
they are ``.. begin key`` and ``.. end key``. A begin marker may carry a ``: note``
suffix, which regeneration rewrites to the do-not-edit note.
"""

from __future__ import annotations

from re import DOTALL, Match, Pattern, compile, escape
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from pathlib import Path

type TableFormat = Literal["md", "rst"]

_BEGINS: dict[TableFormat, str] = {
    "md": "<!-- {prefix}{key}: {note} -->\n",
    "rst": ".. begin {prefix}{key}: {note}\n",
}

_OPENERS: dict[TableFormat, str] = {
    "md": r"<!-- {prefix}(?P<key>[\w-]+)(?:: [^>\n]*)? -->",
    "rst": r"\.\. begin {prefix}(?P<key>[\w-]+)",
}

_MARKERS: dict[TableFormat, str] = {
    "md": (
        r"<!-- {prefix}{key}(?:: [^>\n]*)? -->\n"
        r".*?(?P<end><!-- /{prefix}(?P=key) -->)"
    ),
    "rst": (
        r"\.\. begin {prefix}{key}(?:: [^\n]*)?\n"
        r".*?(?P<end>\.\. end {prefix}(?P=key))"
    ),
}


def build_block_pattern(
    keys: Iterable[str], fmt: TableFormat = "md", prefix: str = ""
) -> Pattern[str]:
    """
    Builds the pattern matching a document's marked blocks.

    Args:

        keys: The block keys to match; longer keys are tried first.

    Kwargs:

        fmt: The document's markup.
        prefix: The text every marker puts before its key, such as ``"api-surface:"``.

    Returns:

        A pattern whose matches carry the block's ``key`` and its ``end`` marker.

    Examples:

        >>> pattern = build_block_pattern(["rules"])
        >>> pattern.search("<!-- rules -->\\nold\\n<!-- /rules -->")["key"]
        'rules'

    """
    ordered = sorted(keys, key=len, reverse=True)
    key = rf"(?P<key>{'|'.join(map(escape, ordered))})"
    marker = _MARKERS[fmt].format(prefix=escape(prefix), key=key)
    return compile(marker, DOTALL)


def build_marker_pattern(prefix: str, fmt: TableFormat = "md") -> Pattern[str]:
    """
    Builds the pattern matching every begin marker that carries a prefix.

    Unlike :func:`build_block_pattern`, it accepts any key, so a misspelled or
    unclosed block still matches.

    Args:

        prefix: The text every marker puts before its key, such as ``"api-surface:"``.

    Kwargs:

        fmt: The document's markup.

    Returns:

        A pattern whose matches carry the marker's ``key``.

    Examples:

        >>> pattern = build_marker_pattern("plan-")
        >>> pattern.search("<!-- plan-tabel -->\\n")["key"]
        'tabel'

    """
    return compile(_OPENERS[fmt].format(prefix=escape(prefix)))


def generate_blocks(
    text: str,
    pattern: Pattern[str],
    render: Callable[[str], str],
    note: str,
    fmt: TableFormat = "md",
    prefix: str = "",
) -> str:
    """
    Generates every marked block of a document from its key.

    Args:

        text: The document holding the marked blocks.
        pattern: The block pattern, from :func:`build_block_pattern`.
        render: Renders one block's body, ending in a newline, from its key.
        note: The do-not-edit note each begin marker carries.

    Kwargs:

        fmt: The document's markup.
        prefix: The text every marker puts before its key.

    Returns:

        The document with each marked block regenerated.

    Examples:

        >>> pattern = build_block_pattern(["rules"])
        >>> text = "<!-- rules -->\\nold\\n<!-- /rules -->"
        >>> print(generate_blocks(text, pattern, str.upper, "Generated."))
        <!-- rules: Generated. -->
        RULES<!-- /rules -->

    """

    def _replace(match: Match[str]) -> str:
        key = match["key"]
        begin = _BEGINS[fmt].format(prefix=prefix, key=key, note=note)
        return f"{begin}{render(key)}{match['end']}"

    return pattern.sub(_replace, text)


def read_doc(path: Path) -> str:
    """Reads a UTF-8 document, or empty text when it is absent."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


def gen_block_offenders(
    path: Path,
    pattern: Pattern[str],
    expected: frozenset[str],
    regenerate: Callable[[str], str],
    selector: str,
    markers: Pattern[str] | None = None,
) -> Iterator[str]:
    """
    Finds a document's marked blocks that are missing or drift from their source.

    Args:

        path: The document; an absent file has no blocks.
        pattern: The block pattern, from :func:`build_block_pattern`.
        expected: The block keys the document must hold.
        regenerate: Regenerates the whole document's blocks.
        selector: The ``manage codegen`` selector that regenerates them.

    Kwargs:

        markers: The open marker pattern, from :func:`build_marker_pattern`; begin
            markers it finds that ``pattern`` does not are reported.

    Yields:

        One message naming the unknown or unclosed blocks, if any, then one naming
        the missing blocks, or else one saying the blocks are stale.

    Examples:

        >>> from pathlib import Path
        >>>
        >>> pattern = build_block_pattern(["rules"])
        >>> offenders = gen_block_offenders(
        ...     Path("absent.md"), pattern, frozenset({"rules"}), str, "--rules"
        ... )
        >>> next(offenders)
        "absent.md: missing blocks ['rules']"

    """
    text = read_doc(path)
    present = {match["key"] for match in pattern.finditer(text)}
    found = set() if markers is None else {m["key"] for m in markers.finditer(text)}

    if unknown := sorted(found - present):
        yield f"{path.name}: unknown or unclosed blocks {unknown}"

    if missing := sorted(expected - present):
        yield f"{path.name}: missing blocks {missing}"
    elif regenerate(text) != text:
        yield f"{path.name}: blocks are stale; run `manage codegen {selector}`"


def build_md_table(table: Sequence[Sequence[str]]) -> str:
    """
    Builds a Markdown table from its header row and body rows.

    Args:

        table: The header row followed by the body rows.

    Returns:

        The table's lines, without a trailing newline.

    Examples:

        >>> print(build_md_table([("Verb", "Rule"), ("`get`", "Reads")]))
        | Verb | Rule |
        | --- | --- |
        | `get` | Reads |

    """
    header, *body = table
    lines = [header, ["---"] * len(header), *body]
    return "\n".join(f"| {' | '.join(line)} |" for line in lines)
