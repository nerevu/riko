# vim: sw=4:ts=4:expandtab
"""Private declaration of the general-purpose function-name verbs."""

from __future__ import annotations

from typing import NamedTuple


class VerbRule(NamedTuple):
    """
    One general-purpose verb a function name may start with.

    Attributes:

        verb: The name prefix.
        meaning: What a function named with it does.
        raises: When it raises.
        returns: What it gives back.
        rule: The test that decides whether the verb fits.
        example: A function that uses it.

    """

    verb: str
    meaning: str
    raises: str
    returns: str
    rule: str
    example: str

    @property
    def lead(self) -> str:
        """The word a docstring summary for this verb starts with."""
        return f"{self.verb.capitalize()}s"


VERBS: tuple[VerbRule, ...] = (
    VerbRule(
        "load",
        "Acquire through an external, ambient, or provider boundary",
        "Acquisition failure normally surfaces",
        "The acquired data or state",
        "**MUST** cross an acquisition boundary",
        "`load_settings`",
    ),
    VerbRule(
        "validate",
        "Check a contract",
        "**MUST** raise for an invalid value",
        "`None`",
        "**MUST NOT** transform or return a replacement value; "
        "observationally idempotent",
        "`Workflow.validate`",
    ),
    VerbRule(
        "require",
        "Enforce that a required value, object, or precondition exists",
        "**MUST** raise when the requirement fails",
        "The value, narrowed to a usable form; `None` for a precondition",
        "**MUST NOT** silently default, repair, or substitute; "
        "**MAY** use lookup or context",
        "`require_str`",
    ),
    VerbRule(
        "resolve",
        "Determine the effective value from a reference, context, fallback, or "
        "precedence",
        "**MUST NOT** treat a missing match as an error when a fallback is part of "
        "the contract; **MAY** raise for invalid input",
        "The effective value, possibly a fallback",
        "**MUST** involve reference, context, fallback, or precedence; chooses what "
        "applies rather than canonicalizing the input",
        "`resolve_format`",
    ),
    VerbRule(
        "parse",
        "Turn a representation or grammar into semantic structure",
        "**MUST** raise for malformed input",
        "A semantic structure of a different type than the input",
        "**MUST NOT** use resolution context; the input is a representation *of* "
        "the output",
        "`Workflow.parse`",
    ),
    VerbRule(
        "normalize",
        "Rewrite an accepted form as its canonical equivalent",
        "**MUST** raise for an invalid form",
        "The canonical form, itself an accepted form",
        "**MUST** be idempotent; **MUST NOT** use resolution context",
        "`normalize_url`",
    ),
    VerbRule(
        "build",
        "Assemble a new semantic artifact",
        "**MAY** raise when construction fails",
        "A new composite artifact",
        "Creates a new artifact from semantic components; dependencies should be "
        "explicit",
        "`build_conf`",
    ),
    VerbRule(
        "get",
        "Query or compute a value from explicit semantic inputs",
        "**MAY** raise for invalid input",
        "Information about the inputs",
        "**MUST NOT** acquire external or ambient state; does not canonicalize or "
        "construct a substantial artifact",
        "`get_document_shape`",
    ),
)


class VerbPair(NamedTuple):
    """
    Two verbs that are easy to mistake for each other.

    Attributes:

        first: One verb of the pair.
        second: The other verb of the pair.
        test: The question that tells them apart.

    """

    first: str
    second: str
    test: str


VERB_PAIRS: tuple[VerbPair, ...] = (
    VerbPair("get", "load", "Does it read external or ambient state? Then `load`."),
    VerbPair(
        "validate",
        "require",
        "Does it return the checked value, or guard a precondition before an action? "
        "Then `require`; `validate` checks a contract and returns `None`.",
    ),
    VerbPair(
        "require",
        "resolve",
        "Does absence get a fallback? Then `resolve`; `require` raises instead.",
    ),
    VerbPair(
        "resolve",
        "normalize",
        "Does the contract fix the default (`normalize`), or does the caller supply "
        "it (`resolve`)?",
    ),
    VerbPair(
        "parse",
        "normalize",
        "Is the output a different type than the input? Then `parse`.",
    ),
    VerbPair("build", "get", "Is the result a substantial new artifact? Then `build`."),
)
