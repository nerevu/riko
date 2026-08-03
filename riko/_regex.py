# vim: sw=4:ts=4:expandtab
"""
riko._regex
~~~~~~~~~~~
Regex rule construction and multi-pass substitution.
"""

import itertools as it
import re
from collections.abc import Iterable, Sequence
from dataclasses import is_dataclass
from operator import itemgetter

from riko import DynamicConf
from riko.types.modules import RegexConfRule, RegexRule
from riko.types.values import BasicValue

INVALID_FILECHAR_PATTERN = re.compile(r'[<>:"/\\\|\*?%]')


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


def make_regex_rule(
    f: str, m: str, r: str, seriesmatch: bool = True, default: str | None = None
) -> RegexConfRule:
    return RegexConfRule(
        field=f, match=m, replace=r, seriesmatch=seriesmatch, default=default
    )


# @memoize(TIMEOUT)
def get_regex_rule(
    rule: DynamicConf | RegexConfRule, recompile: bool = False
) -> RegexRule:
    rule = rule if is_dataclass(rule) else RegexConfRule(**rule)
    flags = 0 if rule.casematch else re.IGNORECASE

    if not rule.singlelinematch:
        flags |= re.MULTILINE
        flags |= re.DOTALL

    count: int = 1 if rule.singlelinematch else 0

    if recompile and "$" in rule.replace:
        replace = re.sub(r"\$(\d+)", r"\\\1", rule.replace, count=0)
    else:
        replace = rule.replace

    match = re.compile(rule.match, flags) if recompile else rule.match

    nrule = {
        "count": count,
        "flags": flags,
        "match": match,
        "replace": replace,
        "default": rule.default,
        "field": rule.field,
        "offset": rule.offset or 0,
        "series": rule.seriesmatch,
    }

    return RegexRule(**nrule)


def slugify(text: str) -> str:
    return text.lower().strip().replace(" ", "-")
