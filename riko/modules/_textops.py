# vim: sw=4:ts=4:expandtab
"""
Provides the text substitution, extraction, and naming helpers behind pipe modules.

Attributes:

    PARAMS: Match selectors for ``first`` and ``last``.
    OPS: Handlers for each find ``location``.

"""

from __future__ import annotations

import re
from collections import Counter
from itertools import groupby
from operator import itemgetter
from random import choice
from typing import TYPE_CHECKING, NamedTuple

from riko.base._iterutils import unzip

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from riko.types.modules import FindConfRule, RegexRule

type _Candidate = tuple[int, int, re.Match[str]]

INVALID_FILECHAR_PATTERN = re.compile(r'[<>:"/\\\|\*?%]')

ONSETS = (
    "b",
    "br",
    "cl",
    "cr",
    "d",
    "dr",
    "f",
    "fl",
    "g",
    "gr",
    "k",
    "m",
    "n",
    "p",
    "pl",
    "r",
    "s",
    "sl",
    "st",
    "t",
    "tr",
    "v",
)

VOWELS = "aeiou"
CODAS = ("", "l", "m", "n", "r", "s", "th", "nd", "nt", "ck")

ADJECTIVES = [
    "ancient",
    "autumn",
    "bold",
    "brisk",
    "calm",
    "crimson",
    "gentle",
    "hidden",
    "lucky",
    "misty",
    "rapid",
    "silent",
    "silver",
    "steady",
    "wild",
]

PARAMS: dict[str, Callable[[list[re.Match[str]]], re.Match[str]]] = {
    "first": lambda matches: matches[0],
    "last": lambda matches: matches[-1],
}

OPS: dict[str, Callable[[str, re.Match[str]], str]] = {
    "before": lambda word, match: word[: match.start()],
    "after": lambda word, match: word[match.end() :],
    "at": lambda _, match: match.group(),
}


def gen_name(count: int = 2) -> Iterator[str]:
    yield choice(ADJECTIVES)  # noqa: S311
    yield "-"

    for _ in range(count):
        yield "".join(map(choice, [ONSETS, VOWELS, CODAS]))  # noqa: S311


class Substitution(NamedTuple):
    """Rewritten text and how many replacements produced it."""

    text: str = ""
    replacements: int = 0


def _gen_candidates(word: str, rules: Sequence[RegexRule]) -> Iterator[_Candidate]:
    for pos, rule in enumerate(rules):
        for match in rule["match"].finditer(word):
            yield match.start(), pos, match


def _gen_substitutions(
    word: str, rules: Sequence[RegexRule]
) -> Iterator[tuple[str, int]]:
    """
    Replaces text using several regex rules in one scan of the original text.

    Where matches overlap, the leftmost wins and the earlier rule breaks a tie. A rule
    with ``count`` 1 replaces only the first match it wins.
    """
    candidates = sorted(_gen_candidates(word, rules), key=itemgetter(0, 1))
    counts: Counter[int] = Counter()
    cursor = 0
    empty_at = -1

    for start, position, match in candidates:
        rule = rules[position]
        end = match.end()
        exhausted = 0 < rule["count"] <= counts[position]

        if start < cursor or exhausted or (start == end == empty_at):
            continue

        yield word[cursor:start], 0
        yield match.expand(rule["replace"]), 0
        counts[position] += 1
        cursor = end
        empty_at = end if start == end else -1

    yield word[cursor:], counts.total()


def substitute_pass(previous: Substitution, rules: Sequence[RegexRule]) -> Substitution:
    """
    Replaces text using one pass of regex rules.

    A lone rule rewrites the text on its own. Several rules all match the original
    text in one scan, so none sees another's replacement. The result counts every
    replacement made so far.

    Args:

        previous: The text to rewrite and the replacements already made.
        rules: The compiled regex rules of one pass (see ``gen_rule_passes``).

    Returns:

        The rewritten text and the running replacement count.

    Raises:

        re.error: If a rule's ``replace`` refers to a group its ``match`` lacks.

    Examples:

        >>> from riko.coercion._dataclass import build_regex_conf_rule, build_regex_rule
        >>>
        >>> conf_rules = [
        ...     build_regex_conf_rule("f", "a", "b", seriesmatch=False),
        ...     build_regex_conf_rule("f", "b", "a", seriesmatch=False),
        ... ]
        >>> rules = [build_regex_rule(r) for r in conf_rules]
        >>> substitute_pass(Substitution("ab"), rules)
        Substitution(text='ba', replacements=2)

    """
    if not (word := previous.text):
        current = Substitution()
    elif len(rules) == 1:
        rule = rules[0]
        text, count = rule["match"].subn(rule["replace"], word, rule["count"])
        current = Substitution(text, count)
    else:
        pieces, counts = unzip(_gen_substitutions(word, rules))
        current = Substitution("".join(pieces), sum(counts))

    return Substitution(current.text, previous.replacements + current.replacements)


def gen_rule_passes(rules: Iterable[RegexRule]) -> Iterator[Sequence[RegexRule]]:
    """
    Groups regex rules into passes to apply one after another.

    Each rule in series forms its own pass. Consecutive rules not in series form one
    pass, which ``substitute_pass`` applies in a single scan of the text.

    Args:

        rules: The compiled regex rules, in order.

    Yields:

        Each pass of rules, in order.

    Examples:

        >>> from riko.coercion._dataclass import build_regex_conf_rule, build_regex_rule
        >>>
        >>> conf_rules = [
        ...     build_regex_conf_rule("f", "a", "b"),
        ...     build_regex_conf_rule("f", "b", "c", seriesmatch=False),
        ...     build_regex_conf_rule("f", "c", "d", seriesmatch=False),
        ... ]
        >>> rules = [build_regex_rule(r) for r in conf_rules]
        >>> [len(group) for group in gen_rule_passes(rules)]
        [1, 2]

    """
    for series, group in groupby(rules, key=itemgetter("series")):
        if series:
            yield from ([rule] for rule in group)
        else:
            yield list(group)


def reduce_find(word: str, rule: FindConfRule, literal: bool = False) -> str:
    """
    Extracts the text around the match ``rule`` selects.

    Slicing is by match position, so the original text is preserved exactly.
    Reassembling it from the pattern would corrupt any non-literal ``find``.

    Args:

        word: The string to search.
        rule: The find criteria: ``find``, ``location`` and ``param``.

    Kwargs:

        literal: Whether to treat ``find`` as a literal rather than a regex.

    Returns:

        The stripped extracted text. Nothing matching gives ``""``, except
        ``location="after"`` which gives the whole word.

    Examples:

        >>> from meza.fntools import Objectify
        >>>
        >>> rule = Objectify({"find": "[aiou]", "location": "before"})
        >>> reduce_find("hello world", rule)
        'hell'
        >>> reduce_find("hello world", rule, literal=True)
        ''

    """
    pattern = re.escape(rule.find) if literal else rule.find

    if pattern and (matches := list(re.finditer(pattern, word))):
        pick = PARAMS.get(rule.param or "first", PARAMS["first"])
        op = OPS.get(rule.location, OPS["before"])
        result = op(word, pick(matches))
    else:
        result = word if rule.location == "after" else ""

    return result.strip()
