# vim: sw=4:ts=4:expandtab
"""
Provides the text substitution, extraction, and naming helpers behind pipe modules.

Attributes:

    PARAMS: Match selectors for ``first`` and ``last``.
    OPS: Handlers for each find ``location``.

"""

from __future__ import annotations

import itertools as it
import re
from operator import itemgetter
from random import choice
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from riko.types._scalars import BasicValue
    from riko.types.modules import FindConfRule, RegexRule

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


def _gen_words(match, splits: Iterable[BasicValue]):
    groups = list(it.dropwhile(lambda x: not x, match.groups()))

    for s in splits:
        try:
            num = int(s)
        except ValueError:
            word = s
        else:
            word = next(it.islice(groups, num, num + 1))

        yield word


def gen_name(count: int = 2) -> Iterator[str]:
    yield choice(ADJECTIVES)  # noqa: S311
    yield "-"

    for _ in range(count):
        yield "".join(map(choice, [ONSETS, VOWELS, CODAS]))  # noqa: S311


def multi_substitute(word: str, rules: Sequence[RegexRule]) -> str:
    """
    Replaces the matches of several regex rules in ``word``.

    All rules share one combined pattern and the first rule's ``flags``. A rule's
    ``replace`` may refer to a captured group as ``$n``. Adapted from
    http://code.activestate.com/recipes/576710-multi-regex-single-pass-replace-of-multiple-regexe/

    Args:

        word: The string to rewrite.
        rules: The regex rules, applied in order.

    Returns:

        ``word`` with each rule's matches replaced.

    """
    flags = rules[0]["flags"]
    tuples = ((p, r["match"]) for p, r in enumerate(rules))
    regexes = (f"(?P<match_{p}>{r})" for p, r in tuples)
    pattern = "|".join(regexes)
    regex = re.compile(pattern, flags)
    resplit = re.compile("\\$(\\d+)")
    rules_in_series = filter(itemgetter("series"), rules)
    rules_in_parallel = (r for r in rules if not r["series"])

    try:
        has_parallel = [next(rules_in_parallel)]
    except StopIteration:
        has_parallel = []

    for _ in it.chain(rules_in_series, has_parallel):
        prev_name = None
        prev_is_series = None
        i = 0

        for match in regex.finditer(word):
            items = match.groupdict().items()
            item = next(filter(itemgetter(1), items))

            if not item:
                continue

            name = item[0]
            rule = rules[int(name[6:])]
            series = rule.get("series")
            kwargs = {"count": rule["count"], "series": series}
            is_previous = name == prev_name
            singlematch = kwargs["count"] == 1
            is_series = prev_is_series or kwargs["series"]
            isnt_previous = bool(prev_name) and not is_previous

            if (is_previous and singlematch) or (isnt_previous and is_series):
                continue

            prev_name = name
            prev_is_series = series

            if resplit.findall(rule["replace"]):
                splits = resplit.split(rule["replace"])
                words = _gen_words(match, splits)
            else:
                splits = rule["replace"]
                start = match.start() + i
                end = match.end() + i
                words = [word[:start], splits, word[end:]]
                i += rule["offset"]

            word = "".join(words)

    return word


def substitute(word: str, rule: RegexRule) -> str:
    if word:
        result = rule["match"].subn(rule["replace"], word, rule["count"])
        replaced, replacements = result

        if rule.get("default") is not None and not replacements:
            replaced = rule.get("default")
    else:
        replaced = word

    return replaced


PARAMS: dict[str, Callable[[list[re.Match[str]]], re.Match[str]]] = {
    "first": lambda matches: matches[0],
    "last": lambda matches: matches[-1],
}

OPS: dict[str, Callable[[str, re.Match[str]], str]] = {
    "before": lambda word, match: word[: match.start()],
    "after": lambda word, match: word[match.end() :],
    "at": lambda _, match: match.group(),
}


def reduce_find(word: str, rule: FindConfRule, literal: bool = False) -> str:
    """
    Extracts the text around the match ``rule`` selects.

    Slicing is by match position, so the original text is preserved exactly.
    Reassembling it from the pattern would corrupt any non-literal ``find``.

    Args:

        word: The string to search.
        rule: The find criteria: ``find``, ``location`` and ``param``.
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
