# vim: sw=4:ts=4:expandtab
"""Generates the function-name verb tables from their declaration."""

from __future__ import annotations

from functools import partial
from itertools import chain
from re import compile
from typing import TYPE_CHECKING

from riko.base._funcutils import compose
from riko.base._paths import ROOT_DIR
from riko.base._strutils import get_codegen_note, wrap_words
from riko.base._verbs import VERB_PAIRS, VERBS

from ._gen_blocks import (
    TableFormat,
    build_block_pattern,
    build_md_table,
    generate_blocks,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path
    from re import Pattern

_CODE = compile(r"`([^`]+)`")
_NBSP = "\x00"
_NOTE = get_codegen_note("--verbs")
_OLD, _NEW = "MUST NOT", f"MUST{_NBSP}NOT"

_RST_WIDTHS: dict[str, tuple[int, ...]] = {
    "verbs": (13, 11, 22, 24, 20, 30, 22),
    "verb-rules": (13, 11, 60),
    "verb-pairs": (27, 88),
}

VERB_DOCS: dict[Path, tuple[TableFormat, frozenset[str]]] = {
    ROOT_DIR / "CONTRIBUTING.rst": ("rst", frozenset({"verbs", "verb-pairs"})),
    ROOT_DIR / "CLAUDE.md": ("md", frozenset({"verb-rules", "verb-pairs"})),
}

VERB_PATTERNS: dict[TableFormat, Pattern[str]] = {
    "md": build_block_pattern(_RST_WIDTHS, "md"),
    "rst": build_block_pattern(_RST_WIDTHS, "rst"),
}

_word_lens = compose(partial(map, len), str.split)
_sub = partial(_CODE.sub, r"``\1``")


def _cap(
    line: Iterable[str], joiner: str, start: str | None = None, end: str | None = None
) -> str:
    start = joiner if start is None else start
    end = joiner if end is None else end
    return f"{start}{joiner.join(line)}{end}"


_pipe_cap = partial(_cap, joiner=" | ", start="| ", end=" |")


def _get_table(key: str) -> Sequence[Sequence[str]]:
    if key == "verbs":
        header = ("Verb", "Summary starts with", "Meaning", "Raises", "Returns")
        rows = [
            (f"`{v.verb}`", v.lead, v.meaning, v.raises, v.returns, v.rule, v.example)
            for v in VERBS
        ]
        table = [(*header, "Rule", "Example"), *rows]
    elif key == "verb-rules":
        rows = [(f"`{v.verb}`", v.lead, v.rule) for v in VERBS]
        table = [("Verb", "Summary starts with", "Rule"), *rows]
    else:
        pairs = [(f"`{p.first}` / `{p.second}`", p.test) for p in VERB_PAIRS]
        table = [("Mistaken pair", "Test"), *pairs]

    return table


def __gen_parts(
    wrapped_pairs: Iterable[tuple[Sequence[str], int]], i: int
) -> Iterator[str]:
    for lines, width in wrapped_pairs:
        yield (lines[i] if i < len(lines) else "").replace(_NBSP, " ").ljust(width)


def _render_md(key: str) -> str:
    return f"{build_md_table(_get_table(key))}\n"


def _render_rst(key: str) -> str:
    table = _get_table(key)
    cells = [[_sub(cell).replace(_OLD, _NEW) for cell in row] for row in table]
    cols = zip(*cells, strict=True)
    word_lens = (max(chain.from_iterable(map(_word_lens, col))) for col in cols)
    caps = _RST_WIDTHS[key]
    widths = [max(cap, size) for cap, size in zip(caps, word_lens, strict=True)]
    _rule = lambda char: _cap((char * (width + 2) for width in widths), "+")
    lines = ["", _rule("-")]

    for index, row in enumerate(cells):
        pairs = zip(row, widths, strict=True)
        wrapped = [wrap_words(cell, width) for cell, width in pairs]
        _gen_parts = partial(__gen_parts, list(zip(wrapped, widths, strict=True)))
        lines.extend(_pipe_cap(_gen_parts(i)) for i in range(max(map(len, wrapped))))
        lines.append(_rule("=" if index == 0 else "-"))

    lines.extend(["", ""])
    return "\n".join(lines)


def generate_verb_tables(text: str, fmt: TableFormat) -> str:
    """
    Generates a document's verb tables from the verb declaration.

    Args:

        text: The document with ``verbs``, ``verb-rules``, or ``verb-pairs`` blocks.
        fmt: The document's markup.

    Returns:

        The document with each marked block regenerated.

    Examples:

        >>> text = "<!-- verb-pairs -->\\n<!-- /verb-pairs -->"
        >>> print(generate_verb_tables(text, "md").splitlines()[1])
        | Mistaken pair | Test |

    """
    render = _render_md if fmt == "md" else _render_rst
    return generate_blocks(text, VERB_PATTERNS[fmt], render, _NOTE, fmt)


def main() -> int:
    """Regenerates the verb tables in the contributing guide and ``CLAUDE.md``."""
    for path, (fmt, _) in VERB_DOCS.items():
        path.write_text(generate_verb_tables(path.read_text(), fmt))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
