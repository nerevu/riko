# vim: sw=4:ts=4:expandtab
"""Generates the function-name verb tables from their declaration."""

from __future__ import annotations

from functools import partial
from itertools import chain
from re import DOTALL, Match, Pattern, compile
from textwrap import wrap
from typing import TYPE_CHECKING, Literal

from riko.base._paths import ROOT_DIR
from riko.base._verbs import VERB_PAIRS, VERBS

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

type TableFormat = Literal["md", "rst"]

VERB_BLOCKS: frozenset[str] = frozenset({"verbs", "verb-pairs"})
VERB_DOCS: dict[Path, TableFormat] = {
    ROOT_DIR / "CONTRIBUTING.rst": "rst",
    ROOT_DIR / "CLAUDE.md": "md",
}
_KEY = rf"(?P<key>{'|'.join(sorted(VERB_BLOCKS, reverse=True))})"
_CODE = compile(r"`([^`]+)`")
_RST_WIDTHS: dict[str, tuple[int, ...]] = {
    "verbs": (13, 11, 22, 24, 20, 30, 22),
    "verb-pairs": (27, 88),
}
_NBSP = "\x00"

VERB_PATTERNS: dict[TableFormat, Pattern[str]] = {
    "md": compile(
        rf"(?P<begin><!-- {_KEY} -->\n).*?(?P<end><!-- /(?P=key) -->)", DOTALL
    ),
    "rst": compile(
        rf"(?P<begin>\.\. begin {_KEY}\n).*?(?P<end>\.\. end (?P=key))", DOTALL
    ),
}

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
    else:
        pairs = [(f"`{p.first}` / `{p.second}`", p.test) for p in VERB_PAIRS]
        table = [("Mistaken pair", "Test"), *pairs]

    return table


def _render_md(table: Sequence[Sequence[str]]) -> str:
    header, *body = table
    lines = [header, ["---"] * len(header), *body]
    return "\n".join(map(_pipe_cap, lines))


def _gen_word_lens(*cells: Sequence[str]) -> Iterator[int]:
    for col in zip(*cells, strict=True):
        yield max(chain.from_iterable(map(len, cell.split()) for cell in col))


def _gen_cells(table: Sequence[Sequence[str]]) -> Iterator[list[str]]:
    for row in table:
        yield [_sub(cell).replace("MUST NOT", f"MUST{_NBSP}NOT") for cell in row]


def _gen_widths(caps: Iterable[int], word_lens: Iterable[int]) -> Iterator[int]:
    for cap, word_len in zip(caps, word_lens, strict=True):
        yield max(cap, word_len)


def __gen_parts(
    wrapped_pairs: Iterable[tuple[Sequence[str], int]], i: int
) -> Iterator[str]:
    for lines, width in wrapped_pairs:
        yield (lines[i] if i < len(lines) else "").replace(_NBSP, " ").ljust(width)


def _gen_lines(row: Iterable[str], widths: Sequence[int]) -> Iterator[str]:
    _wrap = partial(wrap, break_long_words=False, break_on_hyphens=False)
    row_pairs = zip(row, widths, strict=True)
    wrapped = [_wrap(cell, width) for cell, width in row_pairs]
    wrapped_pairs = list(zip(wrapped, widths, strict=True))
    _gen_parts = partial(__gen_parts, wrapped_pairs)
    height = max(map(len, wrapped))
    yield from (_pipe_cap(_gen_parts(i)) for i in range(height))


def _render_rst(table: Sequence[Sequence[str]], caps: Sequence[int]) -> str:
    cells = list(_gen_cells(table))
    word_lens = _gen_word_lens(*cells)
    widths = list(_gen_widths(caps, word_lens))
    _rule = lambda char: _cap((char * (width + 2) for width in widths), "+")
    header, *body = cells
    lines = [_rule("-"), *_gen_lines(header, widths), _rule("=")]

    for row in body:
        lines.extend([*_gen_lines(row, widths), _rule("-")])

    return "\n".join(lines)


def generate_verb_tables(text: str, fmt: TableFormat) -> str:
    """
    Generates a document's verb tables from the verb declaration.

    Args:

        text: The document, with marked ``verbs`` and ``verb-pairs`` blocks.
        fmt: The document's markup.

    Returns:

        The document with each marked block regenerated.

    Examples:

        >>> text = "<!-- verb-pairs -->\\n<!-- /verb-pairs -->"
        >>> print(generate_verb_tables(text, "md").splitlines()[1])
        | Mistaken pair | Test |

    """

    def _replace(match: Match[str]) -> str:
        table = _get_table(key := match["key"])

        if fmt == "md":
            body = f"{_render_md(table)}\n"
        else:
            body = f"\n{_render_rst(table, _RST_WIDTHS[key])}\n\n"

        return f"{match['begin']}{body}{match['end']}"

    return VERB_PATTERNS[fmt].sub(_replace, text)


def main() -> int:
    """Regenerates the verb tables in the contributing guide and ``CLAUDE.md``."""
    for path, fmt in VERB_DOCS.items():
        path.write_text(generate_verb_tables(path.read_text(), fmt))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
