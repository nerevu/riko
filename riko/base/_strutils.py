# vim: sw=4:ts=4:expandtab
"""
riko.base._strutils
~~~~~~~~~~~~~~
String helpers: identifier/key sanitization (``replacer``, ``slugify``), regex
rule construction and multi-pass substitution, and the shared find/extract used
by the ``refind`` and ``strfind`` pipes.

Attributes:

    PARAMS: Match selectors for ``first`` and ``last``.
    OPS: Handlers for each find ``location``.

"""

from __future__ import annotations

import itertools as it
import re
from collections.abc import Mapping, Sequence
from operator import itemgetter
from random import choice
from typing import TYPE_CHECKING, cast

from requests.structures import CaseInsensitiveDict

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

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


def replacer(content: str, old: str, new: str = "_") -> str:
    """
    Examples:

        >>> replacer('', '')
        ''
        >>> replacer('1abc', '')
        '_1abc'
        >>> replacer('a.b', '.')
        'a_b'

    """
    if old:
        replaced = content.replace(old, new)
    elif content and (content[0].isdecimal() or not content[0].isascii()):
        replaced = f"{new}{content}"
    else:
        replaced = content

    return replaced


def multi_substitute(word: str, rules: Sequence[RegexRule]) -> str:
    """
    Apply multiple regex rules to 'word'
    http://code.activestate.com/recipes/
    576710-multi-regex-single-pass-replace-of-multiple-regexe/
    """
    flags = rules[0]["flags"]

    # Create a combined regex from the rules
    tuples = ((p, r["match"]) for p, r in enumerate(rules))
    regexes = (f"(?P<match_{p}>{r})" for p, r in tuples)
    pattern = "|".join(regexes)
    regex = re.compile(pattern, flags)
    resplit = re.compile("\\$(\\d+)")

    # For each match, look-up corresponding replace value in dictionary
    rules_in_series = filter(itemgetter("series"), rules)
    rules_in_parallel = (r for r in rules if not r["series"])

    try:
        has_parallel = [next(rules_in_parallel)]
    except StopIteration:
        has_parallel = []

    # print('================')
    # pprint(rules)
    # print('word:', word)
    # print('pattern', pattern)
    # print('flags', flags)

    for _ in it.chain(rules_in_series, has_parallel):
        # print('~~~~~~~~~~~~~~~~')
        # print('new round')
        # print('word:', word)
        # found = list(regex.finditer(word))
        # matchitems = [match.groupdict().items() for match in found]
        # pprint(matchitems)
        prev_name = None
        prev_is_series = None
        i = 0

        for match in regex.finditer(word):
            items = match.groupdict().items()
            item = next(filter(itemgetter(1), items))

            # print('----------------')
            # print('groupdict:', match.groupdict().items())
            # print('item:', item)

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

            # print('name:', name)
            # print('prereplace:', rule['replace'])
            # print('splits:', splits)
            # print('resplits:', resplit.findall(rule['replace']))
            # print('groups:', filter(None, match.groups()))
            # print('i:', i)
            # print('words:', words)
            # print('range:', match.start(), '-', match.end())
            # print('replace:', word)

    # print('substitution:', word)
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

    Slicing is by match position, so the original text is preserved exactly —
    reassembling it from the pattern would corrupt any non-literal ``find``.

    Args:

        word: The string to search.
        rule: The find criteria, holding `find`, `location` and `param`.
        literal: Whether to treat ``find`` as a literal rather than a regex.

    Returns:

        The extracted text, stripped. Nothing matching gives ``""``, except
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
    matches = list(re.finditer(pattern, word)) if pattern else []

    if matches:
        pick = PARAMS.get(rule.param or "first", PARAMS["first"])
        op = OPS.get(rule.location, OPS["before"])
        result = op(word, pick(matches))
    else:
        result = word if rule.location == "after" else ""

    return result.strip()


def slugify(text: str) -> str:
    return text.lower().strip().replace(" ", "-")


def truncate_content[T](content: T | object, length: int = 20) -> T:
    if isinstance(content, str):
        truncated = content[:length] + "…" if len(content) > length else content
    elif isinstance(content, (dict, CaseInsensitiveDict, Mapping)):
        truncated = {k: truncate_content(v) for k, v in content.items()}
    elif isinstance(content, (list, tuple, Sequence)):
        truncated = [truncate_content(v) for v in content]
    else:
        truncated = content

    return cast("T", truncated)
