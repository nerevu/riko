# vim: sw=4:ts=4:expandtab
"""
Loads the planning data: planning phases, milestones, lanes, and their slices.

Structured facts (dates, edges, areas, flags) live in TOML files beside the plans, and
titles and prose live in their Markdown homes. ``PlanningData`` joins the two by id,
derives each status, landing date, and the work order, and reports every problem it
finds. A TOML file whose shape breaks the schema raises ``PlanningError`` while it
builds.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from datetime import date, datetime
from functools import cached_property
from itertools import chain, pairwise
from os.path import relpath
from typing import TYPE_CHECKING, ClassVar, Literal, NamedTuple

import networkx as nx
from attrs import define, field

from riko.base._guards import require_listlike, require_mapping
from riko.base._iterutils import gen_non_null
from riko.base._paths import GAMEPLANS_DIR, SEQUENCE_PATH, TRACKER_PATH
from riko.base._require_guards import (
    require_from_form,
    require_from_keys,
    require_instance,
    require_instances,
)
from riko.types._frozendict import FrozenDict

from ._lint_rst import get_anchor

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

type Status = Literal["planned", "in_design", "in_progress", "complete", "deferred"]
type DecisionStatus = Literal["open", "settled"]
type EdgeKind = Literal["blocked_by", "scheduled_after"]
type NodeKind = Literal["phase", "milestone"]
type Estimate = Literal["S", "M", "L"]
type SectionKind = Literal["heading", "lead_in", "exit"]
type Container = Node | Lane | PlanFile
type ProblemKind = Literal[
    "ids", "graph", "progress", "date", "markdown", "missing_home"
]
type _HomeKind = Literal["home", "area", "reason", "problem"]

_ID = re.compile(r"[A-Za-z0-9-]+")
_TRACK = re.compile(r"[A-Za-z]*")
_DIGITS = re.compile(r"(\d+)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_HEADING = re.compile(r"(?P<hashes>#{1,6}) (?P<text>.+)")
_NODE_HEADING = re.compile(r"(?P<id>[A-Za-z0-9-]+): (?P<title>.+)")
_LEAD_IN = re.compile(r"\*\*(?P<id>[A-Za-z0-9.-]+): (?P<bold>.+?)\*\*(?P<rest>.*)")
_EXIT = re.compile(r"- \*\*(?P<word>ADD|MIGRATE|DELETE):\*\*(?P<rest>.*)")
_GOAL = re.compile(r"\*\*Goal:\*\*\s*(?P<goal>.+?\.)(?=\s|$)", re.DOTALL)
_BLOCK_START = re.compile(r"\s*(?:[-*+]|\d+[.)]|\||(?P<heading>#{1,6}))\s")
_FLIP = re.compile(r"tests/\w+/test_\w+\.py::\w+(?:::\w+)?")
_EDGE_KEYS: tuple[EdgeKind, ...] = ("blocked_by", "scheduled_after")
_TIMING_KEYS = frozenset({"elapsed_days", "active_days", "session_hours"})
_SLICE_ONLY_KEYS = _TIMING_KEYS.union(
    {"designing", "started", "landed", "deferred", "lands_with", "estimate", "flips"}
)
_SLICE_KEYS = _SLICE_ONLY_KEYS.union({"id", *_EDGE_KEYS})
_TITLE_KEYS = frozenset({"title", "name", "summary", "for"})
_CONTAINER_KEYS = _SLICE_ONLY_KEYS.union({"slices", *_EDGE_KEYS})
_PHASE_KEYS = _CONTAINER_KEYS.union({"area", "doc", "decisions"})
_LANE_KEYS = _CONTAINER_KEYS.union({"owner", "trigger"})
_MILESTONE_KEYS = frozenset({*_EDGE_KEYS, "doc", "landed", "proposed"})
_DECISION_KEYS = frozenset({"id", "settled"})
_FILE_KEYS = frozenset({"phases", "milestones", "lanes", "slices"})
_SEQUENCE_DOC = SEQUENCE_PATH.name
_TRACKER_DOC = relpath(TRACKER_PATH, GAMEPLANS_DIR)
_AREAS_HEADING = "Areas"
_STARTED: frozenset[Status] = frozenset({"in_progress", "complete"})
_DONE: frozenset[Status] = frozenset({"complete", "deferred"})
_MET = frozenset({"complete", "settled"})

NEXT_COUNT = 5


class PlanningError(ValueError):
    """A planning TOML file that does not parse or breaks the planning schema."""


class Progress(NamedTuple):
    """
    A derived status and, once complete, its landing date.

    Attributes:

        status: The derived status.
        landed: The landing date, set only when complete.

    """

    status: Status
    landed: date | None = None


class Edge(NamedTuple):
    """
    A declared dependency between two refs.

    Attributes:

        upstream: The ref that comes first.
        downstream: The ref that declares the edge.
        kind: Whether it is a real dependency or only a chosen order.

    """

    upstream: str
    downstream: str
    kind: EdgeKind


class Unlock(NamedTuple):
    """
    One edge out of a ref, with its Markdown reason when one exists.

    Attributes:

        ref: The downstream ref that names the upstream one.
        upstream: The ref it names: the unlocking ref or one of its slices.
        kind: Whether it is a real dependency or only a chosen order.
        reason: The lead-in paragraph in the downstream section explaining the edge.

    """

    ref: str
    upstream: str
    kind: EdgeKind
    reason: Section | None


class Problem(NamedTuple):
    """
    One planning problem.

    Attributes:

        message: A one-line message naming the offending id.
        kind: What sort of problem it is; ``missing_home`` marks an id or area
            whose Markdown home is not written yet.

    """

    message: str
    kind: ProblemKind

    def __str__(self) -> str:
        """Gets the message."""
        return self.message


class _Heading(NamedTuple):
    line: int
    end: int
    level: int
    text: str
    anchor: str
    node: str | None


class _Homes(NamedTuple):
    sections: Mapping[str, Section]
    reasons: Mapping[tuple[str, str], Section]
    areas: frozenset[str]
    problems: tuple[str, ...]


def _natural_key(ref: str) -> tuple[str | int, ...]:
    """Gets a sort key that orders digit runs by value, so ``X4A < X4B < X10``."""
    parts = _DIGITS.split(ref)
    return tuple(int(part) if index % 2 else part for index, part in enumerate(parts))


def _get_track(node_id: str) -> str:
    """Gets the leading letters of a planning phase or milestone id."""
    match = _TRACK.match(node_id)
    return "" if match is None else match[0]


def _require_id(value: object, what: str) -> str:
    """Requires an id made of letters, digits, and hyphens."""
    text = require_instance(str, value, what, error=PlanningError)

    if _ID.fullmatch(text) is None:
        raise PlanningError(f"{what} {text!r} must use only letters, digits, and '-'")

    return text


def _require_table(
    value: object, what: str, keys: Collection[str], required: Collection[str] = ()
) -> Mapping[str, object]:
    """Requires a TOML table holding only known keys and no titles."""
    table: Mapping[str, object] = require_mapping(value, what, error=PlanningError)

    if titled := sorted(_TITLE_KEYS.intersection(table)):
        msg = f"{what} has {titled}: titles, names, and reasons belong in Markdown"
        raise PlanningError(msg)

    return require_from_keys(required, keys, what, error=PlanningError)(table)


def _get_optional[T](
    cls: type[T], table: Mapping[str, object], key: str, what: str
) -> T | None:
    """Gets an optional value of one type, rejecting a bool posing as a number."""
    value = table.get(key)
    where = f"{what} {key!r}"

    if isinstance(value, bool) and cls is not bool:
        raise PlanningError(f"{where} must be of type {cls.__name__}, not bool")
    elif isinstance(value, int) and cls is float:
        value = float(value)

    if value is None:
        found = None
    else:
        found = require_instance(cls, value, where, error=PlanningError)

    return found


def _get_date(table: Mapping[str, object], key: str, what: str) -> date | None:
    """Gets an optional TOML local date, rejecting a datetime or a bare flag."""
    value = table.get(key)

    if isinstance(value, datetime) or not (value is None or isinstance(value, date)):
        raise PlanningError(
            f"{what} {key!r} must be a date, not {type(value).__name__}"
        )

    return value


def _get_refs(table: Mapping[str, object], key: str, what: str) -> tuple[str, ...]:
    """Gets an optional list of refs."""
    where = f"{what} {key!r}"
    values = require_listlike(table.get(key, ()), where, error=PlanningError)
    return tuple(require_instances(str, values, where, error=PlanningError))


def _get_tables(
    table: Mapping[str, object], key: str, what: str
) -> Iterable[tuple[str, object]]:
    """Gets the id-keyed subtables of a TOML table."""
    tables: Mapping[str, object] = require_mapping(
        table.get(key, {}), f"{what} {key!r}", error=PlanningError
    )
    return tables.items()


def _build_slices(container: str, what: str, **table: object) -> tuple[Slice, ...]:
    """Builds a container's slices, or its one implicit slice when it lists none."""
    if "slices" in table:
        if carried := sorted(_SLICE_ONLY_KEYS.intersection(table)):
            raise PlanningError(f"{what} lists slices, so {carried} belong on them")

        where = f"{what} 'slices'"
        entries = require_listlike(table["slices"], where, error=PlanningError)
        whats = (
            (f"{what}.slices[{index}]", entry) for index, entry in enumerate(entries)
        )
        slices = tuple(
            Slice.from_table(container, _require_table(e, w, _SLICE_KEYS, ("id",)), w)
            for w, e in whats
        )
    else:
        implicit = {k: v for k, v in table.items() if k in _SLICE_ONLY_KEYS}
        slices = (Slice.from_table(container, implicit, what),)

    return slices


def _freeze_docs(docs: Mapping[str, str]) -> FrozenDict[str, str]:
    """Freezes the Markdown texts keyed by path."""
    return FrozenDict(docs)


def _combine(*progresses: Progress) -> Progress:
    """Combines slice progress into its container's progress."""
    statuses = {progress.status for progress in progresses}
    dates = (progress.landed for progress in progresses)
    landed = max(gen_non_null(dates), default=None)

    if "complete" in statuses and statuses <= _DONE:
        result = Progress("complete", landed)
    elif statuses == {"deferred"}:
        result = Progress("deferred")
    elif statuses & _STARTED:
        result = Progress("in_progress")
    elif "in_design" in statuses:
        result = Progress("in_design")
    else:
        result = Progress("planned")

    return result


def gen_paragraphs(lines: Sequence[str]) -> Iterator[tuple[int, Sequence[str]]]:
    """
    Generates each Markdown paragraph, list item, table row, and heading.

    A block ends at a blank line or before a line that opens a list item, table row,
    or heading. A heading is always a block of its own.

    Args:

        lines: The Markdown's lines.

    Yields:

        Each block's first line index and its lines.

    Examples:

        >>> list(gen_paragraphs(["# Title", "Intro", "1) item", "", "Last"]))
        [(0, ['# Title']), (1, ['Intro']), (2, ['1) item']), (4, ['Last'])]

    """
    start: int | None = None
    heading = False

    for index, line in enumerate(chain(lines, [""])):
        blank = not line.strip()
        match = _BLOCK_START.match(line)

        if start is not None and (blank or heading or match):
            yield start, lines[start:index]
            start = None

        if not blank and start is None:
            start, heading = index, match is not None and match["heading"] is not None


def _gen_headings(lines: Sequence[str]) -> Iterator[_Heading]:
    """Generates every heading, its section end, and its unique GitHub anchor."""
    found = [
        (index, len(match["hashes"]), match["text"].strip())
        for index, line in enumerate(lines)
        if (match := _HEADING.match(line))
    ]
    counts: Counter[str] = Counter()

    for position, (index, level, text) in enumerate(found):
        later = (i for i, lv, _ in found[position + 1 :] if lv <= level)
        base = get_anchor(text)
        anchor = base if counts[base] == 0 else f"{base}-{counts[base]}"
        counts[base] += 1
        node = _NODE_HEADING.fullmatch(text) if 2 <= level <= 4 else None
        node_id = None if node is None else node["id"]
        yield _Heading(index, next(later, len(lines)), level, text, anchor, node_id)


def gen_sections(doc: str, text: str) -> Iterator[Section]:
    """
    Generates the planning headings, lead-ins, and exit bullets of a Markdown file.

    Fenced code blocks are skipped. A heading section runs to the next heading of the
    same or higher level, and a paragraph belongs to the innermost planning heading
    whose section holds it.

    Args:

        doc: The file's path relative to the plans directory.
        text: The file's Markdown.

    Yields:

        Each heading shaped ``<id>: <title>``, then each lead-in paragraph and exit
        bullet in file order.

    Examples:

        >>> text = "### X1: Some title\\n\\n**Goal:** Ship it. Then rest.\\n"
        >>> heading = next(gen_sections("plan.md", text))
        >>> heading.id, heading.anchor, heading.line, heading.detail
        ('X1', 'x1-some-title', 1, 'Ship it.')

    """
    unfenced = _FENCE.sub(lambda match: "\n" * match[0].count("\n"), text)
    lines = unfenced.splitlines()
    headings = list(_gen_headings(lines))

    for heading in headings:
        if heading.node is not None:
            body = "\n".join(lines[heading.line + 1 : heading.end])
            goal = _GOAL.search(body)
            title = _NODE_HEADING.fullmatch(heading.text)
            yield Section(
                kind="heading",
                id=heading.node,
                doc=doc,
                anchor=heading.anchor,
                title=None if title is None else title["title"].strip(),
                detail=None if goal is None else " ".join(goal["goal"].split()),
                line=heading.line + 1,
                heading=heading.text,
            )

    paragraphs = (
        pair for pair in gen_paragraphs(lines) if not _HEADING.match(pair[1][0])
    )

    for start, block_lines in paragraphs:
        block = " ".join(line.strip() for line in block_lines)
        enclosing = [h for h in headings if h.line < start < h.end]
        owners = [h.node for h in enclosing if h.node is not None]
        owner = owners[-1] if owners else None
        anchor = enclosing[-1].anchor if enclosing else ""
        heading_text = enclosing[-1].text if enclosing else None
        in_areas = any(h.level == 2 and h.text == _AREAS_HEADING for h in enclosing)
        exit_item = _EXIT.fullmatch(block)
        lead_in = _LEAD_IN.fullmatch(block)

        if exit_item is not None and owner is not None:
            exit_id = f"{owner}.{exit_item['word'].lower()}"
            detail = exit_item["rest"].strip()
            yield Section(
                kind="exit",
                id=exit_id,
                doc=doc,
                anchor=anchor,
                detail=detail,
                owner=owner,
                line=start + 1,
                heading=heading_text,
            )
        elif lead_in is not None:
            bold = lead_in["bold"].strip()
            yield Section(
                kind="lead_in",
                id=lead_in["id"],
                doc=doc,
                anchor=anchor,
                title=bold.removesuffix(".").strip(),
                detail=" ".join(lead_in["rest"].split()),
                owner=owner,
                in_areas=in_areas,
                closed=bold.endswith("."),
                line=start + 1,
                heading=heading_text,
            )


@define(frozen=True, slots=True)
class Section:
    """
    A titled piece of planning prose in a Markdown file.

    A heading is a planning phase or milestone's home, a lead-in paragraph is a slice,
    decision, area, lane, or edge reason's home, and an exit bullet is an exit slice's
    home.

    Attributes:

        kind: Whether it is a heading, a lead-in paragraph, or an exit bullet.
        id: The id it names (an exit bullet's is its slice's full ref).
        doc: Its file's path relative to the plans directory.
        anchor: The GitHub anchor of its heading, or of the heading it sits under.
        title: Its title, a lead-in's being its bold text minus the final period; for
            an edge reason, the short reason. An exit bullet has none.
        detail: A heading's goal sentence, or the prose after a lead-in's bold text.
        owner: The id of the planning heading whose section holds it.
        in_areas: Whether it sits under the areas heading.
        closed: Whether a lead-in's bold text ends with a period.
        line: The 1-based line it starts on, or ``None`` for a home not read from
            Markdown.
        heading: The text of its heading, or of the heading it sits under.

    """

    kind: SectionKind
    id: str
    doc: str
    anchor: str
    title: str | None = None
    detail: str | None = None
    owner: str | None = None
    in_areas: bool = False
    closed: bool = True
    line: int | None = None
    heading: str | None = None


@define(frozen=True, slots=True)
class Slice:
    """
    A piece of planned work with its own status.

    Attributes:

        container: The id of the planning phase, lane, or plan that owns it.
        id: Its id within the container, or ``None`` for a container's implicit slice.
        designing: When design began.
        started: When the build began.
        landed: When it merged.
        deferred: Whether it is explicitly unscheduled.
        lands_with: The refs it rides with; it lands when every one lands.
        blocked_by: The refs it cannot start without.
        scheduled_after: The refs it is only scheduled after.
        estimate: Its reserved size estimate.
        elapsed_days: Its reserved elapsed time, in days.
        active_days: Its reserved active time, in days.
        session_hours: Its reserved session time, in hours.
        flips: The reserved test ids it flips.

    """

    label: ClassVar[str] = "slice"

    container: str
    id: str | None
    designing: date | None = None
    started: date | None = None
    landed: date | None = None
    deferred: bool = False
    lands_with: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    scheduled_after: tuple[str, ...] = ()
    estimate: Estimate | None = None
    elapsed_days: int | None = None
    active_days: int | None = None
    session_hours: float | None = None
    flips: tuple[str, ...] = ()

    @cached_property
    def ref(self) -> str:
        """The full ref, which is the container's id for an implicit slice."""
        return self.container if self.id is None else f"{self.container}.{self.id}"

    @property
    def is_chained(self) -> bool:
        """Whether it lands on its own and is scheduled, so it joins the slice chain."""
        return not (self.lands_with or self.deferred)

    @cached_property
    def dates(self) -> tuple[tuple[str, date], ...]:
        """The named dates that are present."""
        named = (
            ("designing", self.designing),
            ("started", self.started),
            ("landed", self.landed),
        )
        return tuple((name, value) for name, value in named if value is not None)

    @classmethod
    def from_table(
        cls, container: str, table: Mapping[str, object], what: str
    ) -> Slice:
        """
        Builds a slice from its key-checked TOML table.

        Raises:

            PlanningError: If its landing keys conflict, its dates are out of order, it
                carries timing without landing, or a value has the wrong type.

        """
        slice_id = table.get("id")
        given = table.get("estimate")
        require_estimate = require_from_form(Estimate, error=PlanningError)

        if given is None:
            estimate = None
        else:
            estimate = require_estimate(given, f"{what} 'estimate'")

        built = cls(
            container=container,
            id=None if slice_id is None else _require_id(slice_id, f"{what} 'id'"),
            designing=_get_date(table, "designing", what),
            started=_get_date(table, "started", what),
            landed=_get_date(table, "landed", what),
            deferred=_get_optional(bool, table, "deferred", what) is True,
            lands_with=_get_refs(table, "lands_with", what),
            blocked_by=_get_refs(table, "blocked_by", what),
            scheduled_after=_get_refs(table, "scheduled_after", what),
            estimate=estimate,
            elapsed_days=_get_optional(int, table, "elapsed_days", what),
            active_days=_get_optional(int, table, "active_days", what),
            session_hours=_get_optional(float, table, "session_hours", what),
            flips=_get_refs(table, "flips", what),
        )
        landings = (built.landed is not None, bool(built.lands_with), built.deferred)
        days = [value for _, value in built.dates]

        if sum(landings) > 1:
            msg = f"{what}: 'landed', 'lands_with', and 'deferred' exclude each other"
            raise PlanningError(msg)
        elif days != sorted(days):
            msg = f"{what}: dates must run designing, then started, then landed"
            raise PlanningError(msg)
        elif built.landed is None and _TIMING_KEYS.intersection(table):
            raise PlanningError(f"{what}: timing fields need a 'landed' date")

        return built

    def get_progress(self, lookup: Mapping[str, Progress]) -> Progress:
        """
        Gets its progress, reading each host's progress from ``lookup``.

        A rider is complete once every host is, and lands on the latest host landing.
        """
        hosts = [lookup.get(host) for host in self.lands_with]
        done = [host for host in gen_non_null(hosts) if host.status == "complete"]
        host_dates = [host.landed for host in done if host.landed is not None]

        if self.landed is not None:
            result = Progress("complete", self.landed)
        elif hosts and len(done) == len(hosts):
            result = Progress("complete", max(host_dates, default=None))
        elif self.deferred:
            result = Progress("deferred")
        elif self.started is not None:
            result = Progress("in_progress")
        elif self.designing is not None:
            result = Progress("in_design")
        else:
            result = Progress("planned")

        return result


@define(frozen=True, slots=True)
class Decision:
    """
    An open question that work may wait on.

    Attributes:

        container: The id of the planning phase that owns it.
        id: Its id within the container.
        settled: When it was settled; absent while it is open.

    """

    label: ClassVar[str] = "decision"

    container: str
    id: str
    settled: date | None = None

    @cached_property
    def ref(self) -> str:
        """The full ref."""
        return f"{self.container}.{self.id}"

    @property
    def status(self) -> DecisionStatus:
        """Whether it is open or settled."""
        return "open" if self.settled is None else "settled"

    @classmethod
    def from_table(cls, container: str, value: object, what: str) -> Decision:
        """Builds a decision from its TOML table."""
        table = _require_table(value, what, _DECISION_KEYS, ("id",))
        decision_id = _require_id(table["id"], f"{what} 'id'")
        return cls(container, decision_id, _get_date(table, "settled", what))


@define(frozen=True, slots=True)
class Node:
    """
    A planning phase or milestone.

    Attributes:

        kind: Whether it is a planning phase or a milestone.
        id: Its id.
        doc: The file holding its heading, when not its track's default.
        area: Its area key.
        blocked_by: The refs it cannot start without.
        scheduled_after: The refs it is only scheduled after.
        slices: A planning phase's slices, or its one implicit slice.
        decisions: A planning phase's open or settled questions.
        landed: When a milestone landed.
        proposed: Whether a milestone is not yet an accepted plan.

    """

    kind: NodeKind
    id: str
    doc: str | None = None
    area: str | None = None
    blocked_by: tuple[str, ...] = ()
    scheduled_after: tuple[str, ...] = ()
    slices: tuple[Slice, ...] = ()
    decisions: tuple[Decision, ...] = ()
    landed: date | None = None
    proposed: bool = False

    @property
    def label(self) -> str:
        """The kind in plain English."""
        return "planning phase" if self.kind == "phase" else "milestone"

    @property
    def track(self) -> str:
        """The leading letters of its id."""
        return _get_track(self.id)

    @cached_property
    def home(self) -> str:
        """The file holding its heading, relative to the plans directory."""
        if self.doc is not None:
            result = self.doc
        elif self.kind == "phase" and self.track == "P":
            result = _TRACKER_DOC
        else:
            result = _SEQUENCE_DOC

        return result

    @classmethod
    def from_phase_table(cls, phase_id: str, value: object, what: str) -> Node:
        """
        Builds a planning phase from its TOML table.

        Raises:

            PlanningError: If the table breaks the schema, or an ``R`` track planning
                phase has no area.

        """
        table = _require_table(value, what, _PHASE_KEYS)
        node_id = _require_id(phase_id, what)
        area = _get_optional(str, table, "area", what)
        where = f"{what} 'decisions'"
        decisions = require_listlike(
            table.get("decisions", ()), where, error=PlanningError
        )

        if area is None and _get_track(node_id) == "R":
            raise PlanningError(f"{what}: missing 'area'")

        return cls(
            kind="phase",
            id=node_id,
            doc=_get_optional(str, table, "doc", what),
            area=area,
            blocked_by=_get_refs(table, "blocked_by", what),
            scheduled_after=_get_refs(table, "scheduled_after", what),
            slices=_build_slices(node_id, what, **table),
            decisions=tuple(
                Decision.from_table(node_id, entry, f"{what}.decisions[{index}]")
                for index, entry in enumerate(decisions)
            ),
        )

    @classmethod
    def from_milestone_table(cls, milestone_id: str, value: object, what: str) -> Node:
        """Builds a milestone from its TOML table."""
        table = _require_table(value, what, _MILESTONE_KEYS)
        return cls(
            kind="milestone",
            id=_require_id(milestone_id, what),
            doc=_get_optional(str, table, "doc", what),
            blocked_by=_get_refs(table, "blocked_by", what),
            scheduled_after=_get_refs(table, "scheduled_after", what),
            landed=_get_date(table, "landed", what),
            proposed=_get_optional(bool, table, "proposed", what) is True,
        )

    def get_progress(self, lookup: Mapping[str, Progress]) -> Progress:
        """
        Gets its progress, reading its slices' hosts and prerequisites from ``lookup``.

        A milestone is complete once landed and in progress once any of its own
        prerequisites is complete; a planning phase combines its slices.
        """
        found = (lookup.get(ref) for ref in self.blocked_by)
        statuses = {progress.status for progress in gen_non_null(found)}

        if self.kind == "phase":
            result = _combine(*(item.get_progress(lookup) for item in self.slices))
        elif self.landed is not None:
            result = Progress("complete", self.landed)
        elif "complete" in statuses:
            result = Progress("in_progress")
        else:
            result = Progress("planned")

        return result


@define(frozen=True, slots=True)
class Lane:
    """
    Housekeeping work beside the dependency graph.

    Attributes:

        id: Its id.
        owner: Who lands it; required when it or one of its slices self-lands.
        trigger: When it lands.
        blocked_by: The refs it cannot start without.
        scheduled_after: The refs it is only scheduled after.
        slices: Its slices, or its one implicit slice.

    """

    label: ClassVar[str] = "lane"
    decisions: ClassVar[tuple[Decision, ...]] = ()

    id: str
    owner: str | None = None
    trigger: str | None = None
    blocked_by: tuple[str, ...] = ()
    scheduled_after: tuple[str, ...] = ()
    slices: tuple[Slice, ...] = ()

    @classmethod
    def from_table(cls, lane_id: str, value: object, what: str) -> Lane:
        """
        Builds a lane from its TOML table.

        Raises:

            PlanningError: If the table breaks the schema, or it self-lands without an
                owner.

        """
        table = _require_table(value, what, _LANE_KEYS)
        node_id = _require_id(lane_id, what)
        owner = _get_optional(str, table, "owner", what)
        slices = _build_slices(node_id, what, **table)

        if owner is None and any(not item.lands_with for item in slices):
            raise PlanningError(f"{what}: missing 'owner' for a self-landing slice")

        return cls(
            id=node_id,
            owner=owner,
            trigger=_get_optional(str, table, "trigger", what),
            blocked_by=_get_refs(table, "blocked_by", what),
            scheduled_after=_get_refs(table, "scheduled_after", what),
            slices=slices,
        )

    def get_progress(self, lookup: Mapping[str, Progress]) -> Progress:
        """Gets its progress by combining its slices'."""
        return _combine(*(item.get_progress(lookup) for item in self.slices))


@define(frozen=True, slots=True)
class PlanFile:
    """
    One planning TOML file.

    A file that lists top-level slices is itself a container whose id is its stem.

    Attributes:

        id: The file's stem.
        phases: The planning phases it declares.
        milestones: The milestones it declares.
        lanes: The lanes it declares.
        slices: Its own top-level slices.

    """

    label: ClassVar[str] = "plan"
    decisions: ClassVar[tuple[Decision, ...]] = ()
    blocked_by: ClassVar[tuple[str, ...]] = ()
    scheduled_after: ClassVar[tuple[str, ...]] = ()

    id: str
    phases: tuple[Node, ...] = ()
    milestones: tuple[Node, ...] = ()
    lanes: tuple[Lane, ...] = ()
    slices: tuple[Slice, ...] = ()

    @cached_property
    def docs(self) -> frozenset[str]:
        """The Markdown files it needs, relative to the plans directory."""
        homes = (node.home for node in chain(self.phases, self.milestones))
        return frozenset({f"{self.id}.md", _SEQUENCE_DOC, *homes})

    @classmethod
    def from_toml(cls, stem: str, data: Mapping[str, object]) -> PlanFile:
        """
        Builds a plan file from its parsed TOML.

        Raises:

            PlanningError: If the file breaks the schema; the message names the file
                and key.

        """
        what = f"{stem}.toml"
        table = _require_table(data, what, _FILE_KEYS)
        phases = _get_tables(table, "phases", what)
        milestones = _get_tables(table, "milestones", what)
        lanes = _get_tables(table, "lanes", what)
        return cls(
            id=stem,
            phases=tuple(
                Node.from_phase_table(key, value, f"{what} phases.{key}")
                for key, value in phases
            ),
            milestones=tuple(
                Node.from_milestone_table(key, value, f"{what} milestones.{key}")
                for key, value in milestones
            ),
            lanes=tuple(
                Lane.from_table(key, value, f"{what} lanes.{key}")
                for key, value in lanes
            ),
            slices=_build_slices(stem, what, **table) if "slices" in table else (),
        )

    def get_progress(self, lookup: Mapping[str, Progress]) -> Progress:
        """Gets its progress by combining its slices'."""
        return _combine(*(item.get_progress(lookup) for item in self.slices))


@define(frozen=True, slots=True)
class PlanningData:
    """
    Every planning file and Markdown home, joined by id, with their derived views.

    Attributes:

        plans: The planning TOML files.
        docs: The Markdown text of each home, keyed by its path relative to the plans
            directory.

    Examples:

        >>> from datetime import date
        >>>
        >>> phase = {"doc": "plan.md", "landed": date(2026, 1, 2)}
        >>> milestone = {"doc": "plan.md", "blocked_by": ["X1"]}
        >>> plan = {"phases": {"X1": phase}, "milestones": {"MX": milestone}}
        >>> text = "## X1: First\\n\\n## MX: Done\\n"
        >>> data = PlanningData.from_documents({"plan": plan}, {"plan.md": text})
        >>> data.get_status("X1"), data.get_landed("X1"), data.get_leg("X1")
        ('complete', datetime.date(2026, 1, 2), 'MX')
        >>> list(data.gen_problems(date(2026, 1, 3)))
        []

    """

    plans: tuple[PlanFile, ...]
    docs: Mapping[str, str] = field(
        factory=FrozenDict[str, str], converter=_freeze_docs
    )

    @classmethod
    def from_documents(
        cls, tomls: Mapping[str, Mapping[str, object]], docs: Mapping[str, str]
    ) -> PlanningData:
        """
        Builds planning data from parsed TOML and Markdown text.

        Args:

            tomls: Each planning file's parsed TOML, keyed by file stem.
            docs: Each Markdown home's text, keyed by its path relative to the plans
                directory.

        Returns:

            The joined planning data.

        Raises:

            PlanningError: If a TOML file breaks the schema.

        """
        plans = tuple(PlanFile.from_toml(stem, data) for stem, data in tomls.items())
        return cls(plans, docs)

    @cached_property
    def _owners(self) -> tuple[Container, ...]:
        groups = (
            (
                *plan.phases,
                *plan.milestones,
                *plan.lanes,
                *([plan] if plan.slices else []),
            )
            for plan in self.plans
        )
        return tuple(chain.from_iterable(groups))

    @cached_property
    def containers(self) -> Mapping[str, Container]:
        by_id: dict[str, Container] = {}

        for owner in self._owners:
            by_id.setdefault(owner.id, owner)

        return by_id

    @cached_property
    def slices(self) -> Mapping[str, Slice]:
        """Every slice, implicit ones included, keyed by ref."""
        slices: dict[str, Slice] = {}

        for item in chain.from_iterable(owner.slices for owner in self._owners):
            slices.setdefault(item.ref, item)

        return slices

    @cached_property
    def decisions(self) -> Mapping[str, Decision]:
        """Every decision, keyed by ref."""
        decisions: dict[str, Decision] = {}

        for item in chain.from_iterable(owner.decisions for owner in self._owners):
            decisions.setdefault(item.ref, item)

        return decisions

    @cached_property
    def refs(self) -> frozenset[str]:
        """Every known ref: containers, milestones, slices, and decisions."""
        return frozenset(chain(self.containers, self.slices, self.decisions))

    @cached_property
    def edges(self) -> tuple[Edge, ...]:
        """Every declared ``blocked_by`` and ``scheduled_after`` edge."""
        declaring = chain(
            self._owners, chain.from_iterable(owner.slices for owner in self._owners)
        )
        return tuple(
            Edge(upstream, item.ref if isinstance(item, Slice) else item.id, kind)
            for item in declaring
            for kind, upstreams in zip(
                _EDGE_KEYS, (item.blocked_by, item.scheduled_after), strict=True
            )
            for upstream in upstreams
        )

    @cached_property
    def blocking_edges(self) -> tuple[Edge, ...]:
        """Every declared ``blocked_by`` edge, without the chosen orders."""
        return tuple(edge for edge in self.edges if edge.kind == "blocked_by")

    @cached_property
    def _entries(self) -> Mapping[str, str]:
        """Each container's first self-landing slice, which its own edges apply to."""
        firsts = (
            (owner.id, next((s.ref for s in owner.slices if s.is_chained), owner.id))
            for owner in self._owners
        )
        return dict(firsts)

    def _get_blockers(self, item: Slice) -> tuple[str, ...]:
        """Gets a slice's blockers, with its container's when it lands on its own."""
        owner = self.containers.get(item.container)
        inherited = () if owner is None or item.lands_with else owner.blocked_by
        return (*item.blocked_by, *inherited)

    @cached_property
    def _graph(self) -> nx.DiGraph[str]:
        graph: nx.DiGraph[str] = nx.DiGraph()
        graph.add_nodes_from(chain(self.containers, self.slices))

        for owner in self._owners:
            refs = [item.ref for item in owner.slices if item.ref != owner.id]
            landers = [item.ref for item in owner.slices if item.is_chained]
            graph.add_edges_from((ref, owner.id) for ref in refs)
            graph.add_edges_from(pairwise(landers))

        for item in self.slices.values():
            hosts = (host for host in item.lands_with if host in graph)
            graph.add_edges_from((host, item.ref) for host in hosts)

        for edge in self.edges:
            if edge.upstream in graph:
                target = self._entries.get(edge.downstream, edge.downstream)
                graph.add_edge(edge.upstream, target)

        return graph

    @cached_property
    def _groups(self) -> list[list[str]]:
        components = nx.strongly_connected_components(self._graph)
        return [sorted(group, key=_natural_key) for group in components]

    @cached_property
    def order(self) -> tuple[str, ...]:
        """
        Every planning phase, milestone, lane, plan, and slice ref in work order.

        Refs follow their ``blocked_by`` and ``scheduled_after`` edges and the chain of
        each container's self-landing slices; ties sort by natural id, so ``X4A`` comes
        before ``X10``. Refs on a cycle stay together.
        """
        groups = self._groups
        condensed = nx.condensation(self._graph, scc=[set(group) for group in groups])
        indexes = nx.lexicographical_topological_sort(
            condensed, key=lambda index: _natural_key(groups[index][0])
        )
        return tuple(chain.from_iterable(groups[index] for index in indexes))

    @cached_property
    def _positions(self) -> Mapping[str, int]:
        return {ref: index for index, ref in enumerate(self.order)}

    @cached_property
    def _progress(self) -> Mapping[str, Progress]:
        progress: dict[str, Progress] = {}

        for ref in self.order:
            owner = self.containers.get(ref)
            record = self.slices[ref] if owner is None else owner
            progress[ref] = record.get_progress(progress)

        return progress

    def get_status(self, ref: str) -> Status | DecisionStatus:
        """
        Gets a ref's derived status.

        Args:

            ref: A planning phase, milestone, lane, plan, slice, or decision ref.

        Returns:

            The status; a decision's is ``open`` or ``settled``.

        Raises:

            KeyError: If ``ref`` is unknown.

        """
        decision = self.decisions.get(ref)
        return self._progress[ref].status if decision is None else decision.status

    def get_landed(self, ref: str) -> date | None:
        """Gets a ref's derived landing date, or ``None`` until it is complete."""
        progress = self._progress.get(ref)
        return None if progress is None else progress.landed

    def _get_unmet(self, *refs: str) -> tuple[str, ...]:
        """Gets the known refs not yet complete or, for a decision, settled."""
        return tuple(
            ref for ref in refs if ref in self.refs and self.get_status(ref) not in _MET
        )

    @cached_property
    def ready_slices(self) -> tuple[str, ...]:
        """
        Every slice ready to work on, earliest milestone first.

        A slice qualifies when it is self-landing, neither complete nor deferred, and
        every ``blocked_by`` ref of its own and of its container is complete or, for a
        decision, settled. A ``scheduled_after`` ref, like the order of a container's
        slices, only orders work and never holds a slice back. Slices rank by the
        earliest accepted milestone each one feeds (its leg), then by work order, which
        already breaks ties by natural id; a slice that feeds no milestone ranks after
        every slice that does.
        """
        positions = self._positions
        legs = {
            ref: self.get_leg(ref)
            for ref in self.order
            if (item := self.slices.get(ref)) is not None
            and not item.lands_with
            and self._progress[ref].status not in _DONE
            and not self.get_waiting(ref)
        }
        refs = sorted(
            legs,
            key=lambda ref: (
                len(positions) if (leg := legs[ref]) is None else positions[leg],
                positions[ref],
            ),
        )
        return tuple(refs)

    @cached_property
    def next_slices(self) -> tuple[str, ...]:
        """The first few slices to work on next: the head of ``ready_slices``."""
        return self.ready_slices[:NEXT_COUNT]

    @cached_property
    def _unlocks(self) -> Mapping[str, tuple[Unlock, ...]]:
        """Each container's outgoing edges, keyed by the upstream container."""
        unlocks: dict[str, list[Unlock]] = {}

        for edge in self.edges:
            reason = self.reasons.get(
                (edge.downstream.partition(".")[0], edge.upstream)
            )
            unlock = Unlock(edge.downstream, edge.upstream, edge.kind, reason)
            unlocks.setdefault(edge.upstream.partition(".")[0], []).append(unlock)

        return {container: tuple(found) for container, found in unlocks.items()}

    def get_unlocks(self, ref: str) -> tuple[Unlock, ...]:
        """
        Gets what a ref unlocks, each with its Markdown reason when one exists.

        Args:

            ref: The upstream ref: a container, slice, or decision.

        Returns:

            One entry per downstream ref whose ``blocked_by`` or ``scheduled_after``
            names ``ref`` or, for a container, one of its slices or decisions.

        """
        found = self._unlocks.get(ref.partition(".")[0], ())
        return tuple(
            unlock
            for unlock in found
            if unlock.upstream == ref or unlock.upstream.startswith(f"{ref}.")
        )

    def get_waiting(self, ref: str) -> tuple[str, ...]:
        """
        Gets the open decisions and unfinished blockers a slice still waits on.

        A self-landing slice waits on its container's blockers too.
        """
        item = self.slices.get(ref)
        return self._get_unmet(*(() if item is None else self._get_blockers(item)))

    def get_leg(self, ref: str) -> str | None:
        """Gets the earliest accepted milestone that transitively depends on a ref."""
        later = nx.descendants(self._graph, ref) if ref in self._graph else set()
        legs = (
            other
            for other in later
            if isinstance(node := self.containers.get(other), Node)
            and node.kind == "milestone"
            and not node.proposed
        )
        return min(legs, key=self._positions.__getitem__, default=None)

    def _gen_homes(self) -> Iterator[tuple[_HomeKind, str, Section]]:  # noqa: C901
        """Generates each parsed section's role, or a problem naming it."""
        found = (gen_sections(doc, text) for doc, text in self.docs.items())
        pairs = {
            (edge.downstream.partition(".")[0], edge.upstream) for edge in self.edges
        }

        for section in chain.from_iterable(found):
            ref, owner, doc = section.id, section.owner, section.doc
            local = f"{doc.removesuffix('.md')}.{ref}"
            node = self.containers.get(ref)
            where = f"{section.kind.replace('_', '-')} {ref!r} in {doc}"

            if not section.closed:
                msg = f"{where} needs a bold title ending with a period"
                yield "problem", msg, section

            match section.kind:
                case "heading" if isinstance(node, Node) and node.home == doc:
                    yield "home", ref, section
                case "heading" if isinstance(node, Node):
                    pass
                case "heading":
                    yield "problem", f"{where} names no planning id", section
                case "exit" if ref in self.slices:
                    yield "home", ref, section
                case "lead_in" if owner is not None and ref.startswith(f"{owner}."):
                    if ref in self.slices or ref in self.decisions:
                        yield "home", ref, section
                    else:
                        yield "problem", f"{where} names no planning id", section
                case "lead_in" if owner is not None and ref in self.refs:
                    if (owner, ref) in pairs:
                        yield "reason", ref, section
                    else:
                        msg = (
                            f"{where} gives a reason for an edge {owner} does not have"
                        )
                        yield "problem", msg, section
                case "lead_in" if owner is None and section.in_areas:
                    yield "area", ref, section
                case "lead_in" if (
                    owner is None
                    and (item := self.slices.get(ref)) is not None
                    and item.id is not None
                    and isinstance(self.containers.get(item.container), Lane)
                ):
                    yield "home", ref, section
                case "lead_in" if owner is None and local in self.slices:
                    yield "home", local, section
                case "lead_in" if owner is None and isinstance(node, Lane):
                    yield "home", ref, section
                case _:
                    yield "problem", f"{where} names no planning id", section

    @cached_property
    def _homes(self) -> _Homes:
        sections: dict[str, Section] = {}
        reasons: dict[tuple[str, str], Section] = {}
        areas: set[str] = set()
        problems: list[str] = []

        for kind, key, section in self._gen_homes():
            if kind == "problem":
                problems.append(key)
            elif kind == "reason" and section.owner is not None:
                reasons[section.owner, key] = section
            elif key in sections:
                problems.append(f"{key} has more than one Markdown home")
            else:
                sections[key] = section
                areas.update([key] if kind == "area" else [])

        return _Homes(sections, reasons, frozenset(areas), tuple(problems))

    @property
    def sections(self) -> Mapping[str, Section]:
        """Each Markdown home keyed by planning phase, slice, area, or lane id."""
        return self._homes.sections

    @property
    def reasons(self) -> Mapping[tuple[str, str], Section]:
        """Each edge reason keyed by (downstream container, upstream ref)."""
        return self._homes.reasons

    @property
    def areas(self) -> frozenset[str]:
        """The area keys declared in Markdown; each one's home is in ``sections``."""
        return self._homes.areas

    def _gen_id_problems(self) -> Iterator[str]:
        """Generates duplicate ids, unknown refs, decision hosts, and bad flips."""
        counts = Counter(owner.id for owner in self._owners)
        yield from (
            f"id {key} is declared {n} times" for key, n in counts.items() if n > 1
        )

        for owner in self._owners:
            local = Counter(item.ref for item in chain(owner.slices, owner.decisions))
            dupes = (key for key, n in local.items() if n > 1 and key != owner.id)
            yield from (f"id {key} is declared more than once" for key in dupes)

        for edge in self.edges:
            if edge.upstream not in self.refs:
                ref, kind = edge.upstream, edge.kind
                yield f"{edge.downstream} names unknown ref {ref} in {kind}"

        for item in chain.from_iterable(owner.slices for owner in self._owners):
            unknown = (host for host in item.lands_with if host not in self.refs)
            yield from (
                f"{item.ref} names unknown ref {h} in lands_with" for h in unknown
            )
            riding = (host for host in item.lands_with if host in self.decisions)
            yield from (
                f"{item.ref} names decision {h} in lands_with, which never lands"
                for h in riding
            )
            bad = (flip for flip in item.flips if _FLIP.fullmatch(flip) is None)
            yield from (f"{item.ref} names malformed test id {flip!r}" for flip in bad)

    def _gen_graph_problems(self) -> Iterator[str]:
        """Generates cycles and unfinished planning phases that unlock nothing."""
        for group in self._groups:
            if len(group) > 1 or self._graph.has_edge(group[0], group[0]):
                yield f"refs {', '.join(group)} form a cycle"

        for owner in self._owners:
            downstreams = (
                self.containers.get(unlock.ref.partition(".")[0])
                for unlock in self._unlocks.get(owner.id, ())
            )
            consumers = (
                node for node in gen_non_null(downstreams) if node is not owner
            )

            if (
                isinstance(owner, Node)
                and owner.kind == "phase"
                and self._progress[owner.id].status != "complete"
                and next(consumers, None) is None
            ):
                yield f"planning phase {owner.id} unlocks nothing"

    def _gen_progress_problems(self) -> Iterator[str]:
        """Generates landings out of step with their prerequisites and decisions."""
        open_decisions = {
            ref for ref, item in self.decisions.items() if item.settled is None
        }

        for ref, item in self.slices.items():
            progress = self._progress[ref]
            blockers = [b for b in self._get_blockers(item) if b in open_decisions]
            landed = progress.landed
            befores = () if landed is None else self._graph.predecessors(ref)

            if progress.status in _STARTED:
                yield from (f"{ref} started while {b} is open" for b in blockers)

            for before in befores:
                prior = self._progress.get(before)

                if prior is None or prior.status != "complete":
                    yield f"{ref} landed before {before} completed"
                elif (
                    landed is not None
                    and prior.landed is not None
                    and prior.landed > landed
                ):
                    yield f"{ref} landed on {landed}, before {before} landed"

        for owner in self._owners:
            if isinstance(owner, Node) and owner.landed is not None:
                unmet = self._get_unmet(*owner.blocked_by)
                yield from (f"{owner.id} landed before {r} completed" for r in unmet)

    def _gen_date_problems(self, today: date) -> Iterator[str]:
        """Generates dates after ``today``."""
        slice_dates = (
            (item.ref, name, value)
            for item in self.slices.values()
            for name, value in item.dates
        )
        decision_dates = (
            (item.ref, "settled", item.settled) for item in self.decisions.values()
        )
        node_dates = (
            (owner.id, "landed", owner.landed)
            for owner in self._owners
            if isinstance(owner, Node) and owner.kind == "milestone"
        )

        for ref, name, value in chain(slice_dates, decision_dates, node_dates):
            if value is not None and value > today:
                yield f"{ref} has a future {name} date, {value}"

    def _gen_markdown_problems(self) -> Iterator[str]:
        """Generates stray or malformed Markdown and missing Markdown files."""
        yield from self._homes.problems

        for plan in self.plans:
            if f"{plan.id}.md" not in self.docs:
                yield f"{plan.id}.toml has no sibling Markdown file {plan.id}.md"

    def _gen_missing_homes(self) -> Iterator[str]:
        """Generates ids and areas with no Markdown home."""
        for owner in self._owners:
            named = (
                *([] if isinstance(owner, PlanFile) else [(owner.label, owner.id)]),
                *((s.label, s.ref) for s in owner.slices if s.id is not None),
                *((d.label, d.ref) for d in owner.decisions),
            )
            missing = ((label, ref) for label, ref in named if ref not in self.sections)
            yield from (f"{label} {ref} has no Markdown home" for label, ref in missing)
            area = owner.area if isinstance(owner, Node) else None

            if area is not None and area not in self.areas:
                yield f"planning phase {owner.id} names unknown area {area}"

    def gen_problems(self, today: date) -> Iterator[Problem]:
        """
        Generates every planning problem as a one-line message naming its id.

        Args:

            today: Dates after this are reported as future dates.

        Yields:

            Duplicate ids, unknown refs, malformed test ids, cycles, planning phases
            that unlock nothing, landings out of step with their prerequisites, work
            started under an open decision, future dates, Markdown naming no planning
            id, lead-ins whose bold title lacks a final period, plan files with no
            Markdown file, and ids or areas with no Markdown home, each tagged with
            its kind.

        """
        found: tuple[tuple[ProblemKind, Iterable[str]], ...] = (
            ("ids", self._gen_id_problems()),
            ("graph", self._gen_graph_problems()),
            ("progress", self._gen_progress_problems()),
            ("date", self._gen_date_problems(today)),
            ("markdown", self._gen_markdown_problems()),
            ("missing_home", self._gen_missing_homes()),
        )

        for kind, messages in found:
            yield from (Problem(message, kind) for message in messages)


def load_planning(directory: Path = GAMEPLANS_DIR) -> PlanningData:
    """
    Loads every planning TOML file in a directory and the Markdown homes it names.

    Kwargs:

        directory: The plans directory.

    Returns:

        The joined planning data.

    Raises:

        PlanningError: If a TOML file does not parse or breaks the schema.

    """
    plans: list[PlanFile] = []

    for path in sorted(directory.glob("*.toml")):
        try:
            table = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as error:
            raise PlanningError(f"{path.name} does not parse: {error}") from error

        plans.append(PlanFile.from_toml(path.stem, table))

    names = sorted(set(chain.from_iterable(plan.docs for plan in plans)))
    docs = {
        name: (directory / name).read_text()
        for name in names
        if (directory / name).is_file()
    }
    return PlanningData(tuple(plans), docs)
