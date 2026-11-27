# vim: sw=4:ts=4:expandtab
"""
Generates the forward-track view of the planning data as JSON.

The forward track is one reviewer-facing view of the planning model: the planning
phases on the main track, the accepted milestones, the release history, and a staged
schedule of lanes and steps. It keeps only what its page contract can hold, so other
tracks, edges to work outside that track, and the in-design state drop out. Run as a
module to print the view for the current commit; it exits 1 when the view breaks its
schema or one of the schema's cross-reference checks.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections import Counter
from datetime import date
from typing import TYPE_CHECKING, Literal, NamedTuple

from fastjsonschema import JsonSchemaValueException
from fastjsonschema import compile as fjs_compile

from riko.base._guards import require_listlike, require_mapping
from riko.base._paths import INTERNAL_DOCS_DIR, ROOT_DIR, SEQUENCE_PATH, TRACKER_PATH
from riko.base._require_guards import require_instance

from ._gen_planning import Snapshot, build_plan_url, load_snapshot, read_git
from ._planning import Node, PlanFile, Section, load_planning

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

    from ._planning import EdgeKind, PlanningData, Slice

type _WorkStatus = Literal["planned", "next_up", "in_progress", "complete"]
type _Record = Mapping[str, object]
type _Entry = tuple[str, str, str, str | None]

_PHASE = re.compile(r"R[0-9]+[A-Z]*")
_MILESTONE = re.compile(r"M[0-9]+")
_UNSAFE = re.compile(r"[^a-z0-9_-]+")
_EXITS = ("add", "migrate", "delete")
_LATER = "later"
_TAG_FORMAT = "%(refname:short)|%(creatordate:short)|%(contents:subject)"
_WORK_STATUSES: dict[str, _WorkStatus] = {
    "complete": "complete",
    "in_progress": "in_progress",
    "in_design": "in_progress",
}

SCHEMA_PATH = INTERNAL_DOCS_DIR / "forward-track.schema.json"
PAGE_PATH = INTERNAL_DOCS_DIR / "forward-track.toml"


class Release(NamedTuple):
    """
    A tagged release shown in the history.

    Attributes:

        tag: The tag name.
        day: The tag's creation date.
        title: The tag's message subject, or the tag name when it has none.

    """

    tag: str
    day: date
    title: str


class _Step(NamedTuple):
    id: str
    ref: str
    label: str | None
    stage: str
    lane: str
    members: tuple[str, ...]
    position: int


def _get_title(data: PlanningData, ref: str) -> str:
    """Gets a ref's Markdown title, or the ref itself while it has none."""
    section = data.sections.get(ref)
    title = None if section is None else section.title
    return ref if title is None else title


def _get_detail(data: PlanningData, ref: str) -> str:
    """Gets a ref's goal sentence or lead-in prose, or its title while it has none."""
    section = data.sections.get(ref)
    detail = None if section is None else section.detail
    return _get_title(data, ref) if detail is None or detail == "" else detail


def _normalize_id(text: str) -> str:
    """Normalizes text to a lowercase id of letters, digits, ``_``, and ``-``."""
    return _UNSAFE.sub("-", text.lower()).strip("-_")


def _get_plan_url(data: PlanningData, snapshot: Snapshot, node: Node) -> str:
    """Gets a node's Markdown home link, or its home file's link while it has none."""
    section = data.sections.get(node.id)
    fallback = Section("heading", node.id, node.home, "")
    return build_plan_url(snapshot, fallback if section is None else section)


def _get_link(snapshot: Snapshot, label: str, path: str) -> dict[str, object]:
    """Gets a labelled link to a repository file at the snapshot's commit."""
    url = f"{snapshot.repository}/blob/{snapshot.commit}/{path}"
    return {"label": label, "url": url}


def _gen_work_entries(data: PlanningData, node: Node) -> Iterator[_Entry]:
    """
    Generates a planning phase's work entries: each ref, key, label, and tag.

    A phase with named slices lists them, each followed by the plan-file slices that
    land with it; otherwise it lists its three exit items. Each entry is labelled
    ``<ref> · <title>``: a rider takes the ref of the slice it rides beside its own
    tag, and an exit item the phase id beside its exit word.
    """
    named = [(s, s.id) for s in node.slices if s.id is not None and s.id not in _EXITS]
    riders = [
        item
        for item in data.slices.values()
        if isinstance(data.containers.get(item.container), PlanFile)
    ]
    seen: set[str] = set()

    for item, item_id in named:
        yield (item.ref, item_id, f"{item.ref} · {_get_title(data, item.ref)}", None)

        for rider in riders:
            if item.ref in rider.lands_with and rider.ref not in seen:
                seen.add(rider.ref)
                tag = rider.ref if rider.id is None else rider.id
                label = f"{item.ref} · {_get_title(data, rider.ref)}"
                yield rider.ref, rider.ref, label, tag

    if not named:
        for item in node.slices:
            if item.id is not None and item.id in _EXITS:
                yield item.ref, item.id, f"{node.id} · {item.id.upper()}", None


def _build_work(
    data: PlanningData, snapshot: Snapshot, entries: Iterable[_Entry]
) -> tuple[str, list[dict[str, object]]]:
    """
    Builds a planning phase's work kind and items from its work entries.

    Each item takes its status from the planning data, and an item with a Markdown
    home also links to its paragraph and names where it sits.
    """
    upcoming = frozenset(data.next_slices)
    work: list[dict[str, object]] = []
    keys: set[str] = set()

    for ref, key, label, tag in entries:
        section = data.sections.get(ref)
        location: dict[str, object] = {}

        if section is not None:
            within = section.heading if section.owner is None else section.owner
            trail = (section.doc, within, section.id)
            location = {
                "planUrl": build_plan_url(snapshot, section),
                "location": " › ".join(part for part in trail if part is not None),
            }

        status = _WORK_STATUSES.get(data.get_status(ref), "planned")
        keys.add(key)
        work.append(
            {
                "id": _normalize_id(key),
                **({} if tag is None else {"tag": tag}),
                "title": label,
                "status": "next_up" if ref in upcoming else status,
                "body": _get_detail(data, ref),
                **location,
            }
        )

    kind = "implementation" if keys.issubset(_EXITS) else "slices"
    return kind, work


def _build_dependency(
    data: PlanningData, node: Node, targets: Mapping[str, str]
) -> dict[str, object]:
    """
    Builds what a planning phase unlocks, keeping only targets the view shows.

    A target reached through a real dependency and a chosen order counts as a real
    dependency.
    """
    kinds: dict[str, EdgeKind] = {}
    reasons: list[str] = []

    for unlock in data.get_unlocks(node.id):
        container = unlock.ref.partition(".")[0]
        shown = container != node.id and container in targets
        reason = None if unlock.reason is None else unlock.reason.title

        if shown and kinds.get(container) != "blocked_by":
            kinds[container] = unlock.kind

        if shown and reason is not None and reason not in reasons:
            reasons.append(reason)

    ordered = sorted(kinds, key=data.order.index)
    real = [
        ref
        for ref in ordered
        if kinds[ref] == "blocked_by"
        and not (
            isinstance(target := data.containers.get(ref), Node) and target.proposed
        )
    ]
    chosen = [ref for ref in ordered if kinds[ref] == "scheduled_after"]

    if real:
        kind, badge = "unlocks", f"Unlocks {real[0]}"
    elif chosen:
        kind, badge = "scheduled_before", f"Before {chosen[0]}"
    else:
        kind = "proposed"
        badge = f"Unlocks {ordered[0]}" if ordered else "Unlocks nothing"

    titles = (_get_title(data, ref) for ref in ordered)
    return {
        "kind": kind,
        "badge": badge,
        "detail": "; ".join(reasons) if reasons else ", ".join(titles),
        "targets": [targets[ref] for ref in ordered],
    }


def _gen_steps(
    data: PlanningData, phases: Sequence[Node], milestones: Sequence[Node]
) -> Iterator[_Step]:
    """
    Generates each schedule step, unordered.

    A planning phase whose named slices lead to different milestones appears once per
    milestone; its last appearance also carries its exit items. A milestone sits in
    the lane holding most of its prerequisites.
    """
    positions = {ref: index for index, ref in enumerate(data.order)}
    lanes: dict[str, str] = {}

    for node in phases:
        named = [s for s in node.slices if s.id not in _EXITS and not s.deferred]
        groups: dict[str | None, list[Slice]] = {}

        for item in named:
            groups.setdefault(data.get_leg(item.ref), []).append(item)

        legs = list(groups) if len(groups) > 1 else [data.get_leg(node.id)]
        lane = node.id if node.area is None else node.area
        claimed: set[str] = set()

        for index, leg in enumerate(legs):
            group = groups[leg] if len(legs) > 1 else []
            rest = [item for item in node.slices if item.ref not in claimed]
            slices = rest if index == len(legs) - 1 else group
            claimed.update(item.ref for item in group)
            members = (*(item.ref for item in slices), node.id)
            ranked = (*(item.ref for item in slices if item.is_chained), node.id)
            lanes.update(dict.fromkeys(members, lane))
            yield _Step(
                id=_normalize_id(f"{node.id}-{group[-1].id}" if group else node.id),
                ref=node.id,
                label=_get_title(data, group[-1].ref) if group else None,
                stage=_LATER if leg is None else leg.lower(),
                lane=lane,
                members=members,
                position=min(positions[ref] for ref in ranked),
            )

    for node in milestones:
        found = Counter(lanes[ref] for ref in node.blocked_by if ref in lanes)
        yield _Step(
            id=_normalize_id(node.id),
            ref=node.id,
            label=None,
            stage=node.id.lower(),
            lane=next(iter(found.most_common(1)), (node.id, 0))[0],
            members=(node.id,),
            position=positions[node.id],
        )


def _index_steps(steps: Sequence[_Step]) -> tuple[dict[str, _Step], dict[str, _Step]]:
    """Gets each member ref's last step, then each member ref's first step."""
    last: dict[str, _Step] = {}
    first: dict[str, _Step] = {}

    for step in steps:
        last.update(dict.fromkeys(step.members, step))

        for ref in step.members:
            first.setdefault(ref, step)

    return last, first


def _build_stages(
    data: PlanningData, steps: Sequence[_Step], stages: Sequence[str]
) -> list[dict[str, object]]:
    """Builds each stage that holds a step, its steps grouped into one lane per area."""
    built: list[dict[str, object]] = []

    for stage in stages:
        lanes: dict[str, list[_Step]] = {}

        for step in (step for step in steps if step.stage == stage):
            lanes.setdefault(step.lane, []).append(step)

        if lanes:
            built.append(
                {
                    "id": stage,
                    "lanes": [
                        {
                            "title": _get_title(data, lane),
                            "context": _get_detail(data, lane),
                            "steps": [
                                {
                                    "id": step.id,
                                    "ref": step.ref,
                                    **(
                                        {}
                                        if step.label is None
                                        else {"label": step.label}
                                    ),
                                }
                                for step in members
                            ],
                        }
                        for lane, members in lanes.items()
                    ],
                }
            )

    return built


def _build_bridges(
    data: PlanningData, steps: Sequence[_Step], stages: Sequence[str]
) -> list[dict[str, object]]:
    """
    Builds the real dependencies that cross lanes, one bridge per dependent step.

    Each bridge sits after the stage of its latest input.
    """
    inputs, outputs = _index_steps(steps)
    ranks = {stage: index for index, stage in enumerate(stages)}
    grouped: dict[str, tuple[_Step, dict[str, tuple[_Step, str]]]] = {}

    for edge in data.edges:
        source = inputs.get(edge.upstream)
        target = outputs.get(edge.downstream)
        downstream = edge.downstream.partition(".")[0]
        reason = data.reasons.get((downstream, edge.upstream))
        label = (
            edge.upstream if reason is None or reason.title is None else reason.title
        )

        if (
            edge.kind == "blocked_by"
            and source is not None
            and target is not None
            and source.lane != target.lane
        ):
            ends = grouped.setdefault(target.id, (target, {}))[1]
            ends.setdefault(source.id, (source, label))

    ordered = sorted(grouped.values(), key=lambda pair: pair[0].position)
    return [
        {
            "afterStage": max(
                (source.stage for source, _ in ends.values()), key=ranks.__getitem__
            ),
            "inputs": [
                {"step": source.id, "label": label} for source, label in ends.values()
            ],
            "output": {
                "step": target.id,
                "label": target.ref if target.label is None else target.label,
            },
        }
        for target, ends in ordered
    ]


def _build_outcomes(
    data: PlanningData, steps: Sequence[_Step], nodes: Sequence[Node]
) -> list[dict[str, object]]:
    """Builds each milestone shown after the schedule, after its latest prerequisite."""
    inputs, _ = _index_steps(steps)
    found = (
        (node, [inputs[ref] for ref in node.blocked_by if ref in inputs])
        for node in nodes
    )
    return [
        {
            "id": _normalize_id(node.id),
            "afterStep": max(prior or steps[-1:], key=lambda step: step.position).id,
            "title": _get_title(data, node.id),
            "detail": _get_detail(data, node.id),
            "proposed": node.proposed,
        }
        for node, prior in found
    ]


def build_forward_track(
    data: PlanningData,
    snapshot: Snapshot,
    page: Mapping[str, object],
    history: Sequence[Release],
) -> dict[str, object]:
    """
    Builds the forward-track view of the planning data.

    The focus is the first next slice that belongs to a main-track planning phase,
    with that planning phase's first open decision when it has one. The last accepted
    milestone that no later milestone depends on closes the schedule as an outcome,
    beside the proposed milestones.

    Args:

        data: The planning data.
        snapshot: The commit the links point at, with its unreleased version.
        page: The page copy.
        history: The tagged releases, oldest first.

    Returns:

        The ``snapshot``, ``page``, ``focus``, ``phases``, ``milestones``,
        ``history``, and ``schedule`` of the view.

    Raises:

        ValueError: If no next slice belongs to a main-track planning phase.

    Examples:

        >>> from datetime import date
        >>> from riko.cli._gen_planning import Snapshot
        >>> from riko.cli._planning import PlanningData
        >>>
        >>> milestones = {"M90": {"blocked_by": ["R90"]}}
        >>> plan = {"phases": {"R90": {"area": "core"}}, "milestones": milestones}
        >>> data = PlanningData.from_documents({"plan": plan}, {})
        >>> snapshot = Snapshot("main", "abc1234", date(2026, 1, 1), "https://host/repo")
        >>> track = build_forward_track(data, snapshot, {}, [])
        >>> track["focus"]["phase"], track["phases"][0]["status"]
        ('R90', 'next_up')

    """
    nodes = [n for ref in data.order if isinstance(n := data.containers.get(ref), Node)]
    phases = [n for n in nodes if n.kind == "phase" and _PHASE.fullmatch(n.id)]
    milestones = [
        n for n in nodes if n.kind == "milestone" and _MILESTONE.fullmatch(n.id)
    ]
    accepted = [n for n in milestones if not n.proposed]
    finals = [n for n in accepted if data.get_leg(n.id) is None]
    final = finals[-1] if finals else None
    outcomes = [n for n in milestones if n.proposed or n is final]
    targets = {
        **{n.id: n.id for n in [*phases, *accepted]},
        **{n.id: _normalize_id(n.id) for n in milestones if n.proposed},
    }
    focus = next(
        (
            ref
            for ref in data.next_slices
            if _PHASE.fullmatch(data.slices[ref].container)
            and data.slices[ref].container in targets
        ),
        None,
    )

    if focus is None:
        raise ValueError("no next slice belongs to a main-track planning phase")

    owner = data.slices[focus].container
    legs = (
        data.get_leg(focus),
        data.get_leg(owner),
        None if final is None else final.id,
    )
    decision = next(
        (
            ref
            for ref, item in data.decisions.items()
            if item.container == owner and item.settled is None
        ),
        None,
    )
    landed = {n.id: "landed" for n in phases if data.get_status(n.id) == "complete"}
    steps = sorted(
        _gen_steps(data, phases, [n for n in accepted if n is not final]),
        key=lambda step: step.position,
    )
    stages = [*(n.id.lower() for n in accepted), _LATER]
    events = sorted(
        [
            *((release.day, release.tag, release.title) for release in history),
            *(
                (landed_on, n.id, _get_title(data, n.id))
                for n in phases
                if (landed_on := data.get_landed(n.id)) is not None
            ),
        ],
        key=lambda event: event[0],
    )
    repository = snapshot.repository.rstrip("/")
    return {
        "snapshot": {
            "branch": snapshot.branch,
            "commit": snapshot.commit,
            "date": snapshot.today.isoformat(),
            "unreleasedVersion": snapshot.version,
            "repository": {
                "label": "/".join(repository.split("/")[-2:]),
                "url": snapshot.repository,
            },
            "sources": [
                _get_link(snapshot, path.name, path.relative_to(ROOT_DIR).as_posix())
                for path in (TRACKER_PATH, SEQUENCE_PATH)
            ],
        },
        "page": dict(page),
        "focus": {
            "phase": owner,
            "milestone": next((leg for leg in legs if leg is not None), None),
            "heading": _get_title(data, focus),
            "summary": _get_detail(data, focus),
            **(
                {}
                if decision is None
                else {
                    "decision": {
                        "heading": _get_title(data, decision),
                        "body": _get_detail(data, decision),
                    }
                }
            ),
        },
        "phases": [
            {
                "id": n.id,
                "title": _get_title(data, n.id),
                "purpose": _get_detail(data, n.id),
                "status": landed.get(n.id, "next_up" if n.id == owner else "pending"),
                "planUrl": _get_plan_url(data, snapshot, n),
                "dependency": _build_dependency(data, n, targets),
                "workKind": (
                    work := _build_work(data, snapshot, _gen_work_entries(data, n))
                )[0],
                "work": work[1],
            }
            for n in phases
        ],
        "milestones": [
            {
                "id": n.id,
                "title": _get_title(data, n.id),
                "summary": _get_detail(data, n.id),
                "prerequisiteLabel": " · ".join(n.blocked_by) or "No prerequisites",
                "planUrl": _get_plan_url(data, snapshot, n),
                **({} if n.landed is None else {"date": n.landed.isoformat()}),
            }
            for n in accepted
        ],
        "history": [
            {"when": f"{day.day} {day:%b %Y}", "badge": badge, "title": title}
            for day, badge, title in events
        ],
        "schedule": {
            "stages": _build_stages(data, steps, stages),
            "bridges": _build_bridges(data, steps, stages),
            "outcomes": _build_outcomes(data, steps, outcomes),
        },
    }


def _get_records(record: _Record, key: str) -> list[_Record]:
    """Gets a view record's list of records under ``key``."""
    values = require_listlike(record.get(key, ()), key, error=ValueError)
    return [require_mapping(value, key, error=ValueError) for value in values]


def _get_text(record: _Record, key: str) -> str:
    """Gets a view record's text under ``key``."""
    return require_instance(str, record.get(key), key, error=ValueError)


def _gen_duplicates(kind: str, ids: Sequence[str]) -> Iterator[str]:
    """Generates one message per id that appears more than once."""
    counts = Counter(ids)
    yield from (
        f"{kind} id {key} appears {n} times" for key, n in counts.items() if n > 1
    )


def gen_forward_track_problems(doc: _Record) -> Iterator[str]:
    """
    Finds the cross-reference problems a schema-valid forward-track view can still have.

    Args:

        doc: A forward-track view that already passes its schema.

    Yields:

        One message per repeated id, unresolved reference, or next-up phase other than
        the focus phase.

    Examples:

        >>> doc = {"phases": [{"id": "R90", "status": "next_up", "work": []}]}
        >>> next(gen_forward_track_problems({**doc, "focus": {"phase": "R91"}}))
        'focus phase R91 names no phase'

    """
    phases = _get_records(doc, "phases")
    focus = require_mapping(doc.get("focus", {}), "focus", error=ValueError)
    schedule = require_mapping(doc.get("schedule", {}), "schedule", error=ValueError)
    stages = _get_records(schedule, "stages")
    steps = [
        step
        for stage in stages
        for lane in _get_records(stage, "lanes")
        for step in _get_records(lane, "steps")
    ]
    phase_ids = [_get_text(phase, "id") for phase in phases]
    milestone_ids = [_get_text(item, "id") for item in _get_records(doc, "milestones")]
    outcome_ids = [_get_text(item, "id") for item in _get_records(schedule, "outcomes")]
    nodes = {*phase_ids, *milestone_ids}
    stage_ids = {_get_text(stage, "id") for stage in stages}
    step_ids = {_get_text(step, "id") for step in steps}
    next_up = [_get_text(p, "id") for p in phases if p.get("status") == "next_up"]
    focus_phase, focus_milestone = focus.get("phase"), focus.get("milestone")
    endpoints = [
        (_get_text(end, "step"), "bridge")
        for bridge in _get_records(schedule, "bridges")
        for end in [
            *_get_records(bridge, "inputs"),
            require_mapping(bridge.get("output"), "output", error=ValueError),
        ]
    ]
    afters = [
        *(
            (_get_text(o, "afterStep"), "outcome")
            for o in _get_records(schedule, "outcomes")
        ),
        *endpoints,
    ]
    yield from _gen_duplicates("node", [*phase_ids, *milestone_ids, *outcome_ids])
    yield from _gen_duplicates("stage", [_get_text(stage, "id") for stage in stages])
    yield from _gen_duplicates("step", [_get_text(step, "id") for step in steps])

    for phase, phase_id in zip(phases, phase_ids, strict=True):
        work = [_get_text(item, "id") for item in _get_records(phase, "work")]
        yield from _gen_duplicates(f"phase {phase_id} work", work)
        dependency = require_mapping(phase.get("dependency", {}), "dependency")
        targets = require_listlike(dependency.get("targets", ()), "targets")
        known = nodes.union(outcome_ids)
        yield from (
            f"phase {phase_id} names unknown target {target}"
            for target in targets
            if target not in known
        )

    if focus_phase not in phase_ids:
        yield f"focus phase {focus_phase} names no phase"
    elif next_up != [focus_phase]:
        yield f"next-up phases {next_up} are not the focus phase {focus_phase} alone"

    if focus_milestone not in milestone_ids:
        yield f"focus milestone {focus_milestone} names no milestone"

    yield from (
        f"step {_get_text(step, 'id')} names unknown ref {step.get('ref')}"
        for step in steps
        if step.get("ref") not in nodes
    )
    yield from (
        f"bridge after unknown stage {stage}"
        for bridge in _get_records(schedule, "bridges")
        if (stage := bridge.get("afterStage")) not in stage_ids
    )
    yield from (
        f"{kind} names unknown step {step}"
        for step, kind in afters
        if step not in step_ids
    )


def load_validator() -> Callable[[object], object]:
    """
    Loads the forward-track schema as a validator.

    Returns:

        A callable that returns a valid view and raises
        ``fastjsonschema.JsonSchemaValueException`` at the first violation.

    """
    schema: _Record = require_mapping(
        json.loads(SCHEMA_PATH.read_text()), SCHEMA_PATH.name, error=RuntimeError
    )
    return fjs_compile(dict(schema))


def main() -> int:
    """
    Prints the forward-track view of the planning data for the current commit.

    The view is printed even when it breaks its schema or a cross-reference check;
    the problems go to standard error and the exit status is 1.
    """
    snapshot = load_snapshot()
    page: _Record = tomllib.loads(PAGE_PATH.read_text())
    lines = read_git(
        "for-each-ref", "refs/tags", "--sort=creatordate", f"--format={_TAG_FORMAT}"
    )
    parts = (line.split("|", 2) for line in lines.splitlines() if line)
    history = [
        Release(tag, date.fromisoformat(day), subject or tag)
        for tag, day, subject in parts
    ]
    doc = build_forward_track(load_planning(), snapshot, page, history)

    try:
        load_validator()(doc)
    except JsonSchemaValueException as error:
        problems = [f"schema: {error.message}"]
    else:
        problems = list(gen_forward_track_problems(doc))

    print(json.dumps(doc, indent=2))

    for problem in problems:
        print(problem, file=sys.stderr)

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
