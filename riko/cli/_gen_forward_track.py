# vim: sw=4:ts=4:expandtab
"""
Generates the forward-track view of the planning data as JSON or as one HTML page.

The forward track is one reviewer-facing view of the planning model: the planning
phases on the main track, the accepted milestones, the release history, and the open
planning phases as cards grouped into areas, each placed in a grid by its real
dependencies. It keeps only what its page contract can hold, so other tracks, edges to
work outside that track, chosen orders between cards, and the in-design state drop
out. Run as a module to print the view for the current commit, or with ``--html`` to
write it as a self-contained page instead; it exits 1 when the view breaks its schema
or one of the schema's cross-reference checks, and then writes no page.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from argparse import ArgumentParser
from collections import Counter, deque
from datetime import date
from itertools import chain, count
from typing import TYPE_CHECKING, Literal, NamedTuple

import networkx as nx
from fastjsonschema import JsonSchemaValueException
from fastjsonschema import compile as fjs_compile
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from riko.base._guards import require_listlike, require_mapping
from riko.base._iterutils import gen_instances, gen_non_null
from riko.base._paths import (
    GAMEPLANS_DIR,
    INTERNAL_DOCS_DIR,
    ROOT_DIR,
    SEQUENCE_PATH,
    TRACKER_PATH,
)
from riko.base._require_guards import require_instance

from ._gen_planning import Snapshot, build_plan_url, load_snapshot, read_git
from ._planning import Node, PlanFile, Section, load_planning

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from ._planning import EdgeKind, PlanningData

type _WorkStatus = Literal["planned", "next_up", "in_progress", "complete", "deferred"]
type _Record = Mapping[str, object]
type _Entry = tuple[str, str, str, str | None]
type _Event = tuple[date, str, str, str, str | None]

_PHASE = re.compile(r"R[0-9]+[A-Z]*")
_MILESTONE = re.compile(r"M[0-9]+")
_UNSAFE = re.compile(r"[^a-z0-9_-]+")
_EXITS = ("add", "migrate", "delete")
_PLAIN_RELEASE = re.compile(r"Version \S+ Release")
_TAG_FORMAT = "%(refname:short)|%(creatordate:short)|%(contents:subject)"
_WORK_STATUSES: dict[str, _WorkStatus] = {
    "complete": "complete",
    "in_progress": "in_progress",
    "in_design": "in_progress",
    "deferred": "deferred",
}
_PREREQUISITE_STATUSES: dict[str, str] = {
    "complete": "landed",
    "settled": "landed",
    "in_progress": "next_up",
    "in_design": "next_up",
}

SCHEMA_PATH = INTERNAL_DOCS_DIR / "forward-track.schema.json"
PAGE_PATH = INTERNAL_DOCS_DIR / "forward-track.toml"
VIEW_DIR = INTERNAL_DOCS_DIR / "forward-track"
HTML_PATH = ROOT_DIR / "output" / "forward-track.html"


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


class _Placement(NamedTuple):
    row: int
    column: int
    span: tuple[int, int]
    forked: bool


class _Cell(NamedTuple):
    row: int
    column: int


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


def _build_edges(pairs: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    """Builds the view's edge records from ``(upstream, downstream)`` ref pairs."""
    return [
        {"upstream": _normalize_id(u), "downstream": _normalize_id(v)} for u, v in pairs
    ]


def _get_plan_url(data: PlanningData, snapshot: Snapshot, node: Node) -> str:
    """Gets a node's Markdown home link, or its home file's link while it has none."""
    section = data.sections.get(node.id)
    fallback = Section("heading", node.id, node.home, "")
    return build_plan_url(snapshot, fallback if section is None else section)


def _get_link(snapshot: Snapshot, label: str, path: str) -> dict[str, object]:
    """Gets a labelled link to a repository file at the snapshot's commit."""
    url = f"{snapshot.repository}/blob/{snapshot.commit}/{path}"
    return {"label": label, "url": url}


def _get_when(day: date) -> str:
    """Gets a history event's display date, such as ``3 Nov 2026``."""
    return f"{day.day} {day:%b %Y}"


def _gen_release_events(repository: str, *history: Release) -> Iterator[_Event]:
    """
    Generates the history events for the tagged releases: each date, label, and link.

    The latest release and every release whose tag message says more than its version
    get a row each, linked to its release page; the other releases share one summary
    row dated at the last of them and linked to the release list.

    Examples:

        >>> from datetime import date
        >>>
        >>> tags = ("v1.0", "v1.1", "v2.0")
        >>> days = (date(2024, 1, 2), date(2025, 3, 4), date(2026, 5, 6))
        >>> pairs = zip(tags, days, strict=True)
        >>> history = [Release(t, d, f"Version {t} Release") for t, d in pairs]
        >>> for event in _gen_release_events("https://host/repo", *history):
        ...     print(*event[1:])
        2024–2025 v1.0–v1.1 2 earlier releases https://host/repo/releases
        6 May 2026 v2.0 Version v2.0 Release https://host/repo/releases/tag/v2.0

    """
    earlier = history[:-1]
    plain = [
        r for r in earlier if r.title == r.tag or _PLAIN_RELEASE.fullmatch(r.title)
    ]
    first, last = (plain[0], plain[-1]) if plain else (None, None)

    if first is not None and last is not None:
        years = sorted({first.day.year, last.day.year})
        count = f"{len(plain)} earlier release{'' if len(plain) == 1 else 's'}"
        span = first.tag if first is last else f"{first.tag}–{last.tag}"
        yield last.day, "–".join(map(str, years)), span, count, f"{repository}/releases"

    for release in (*(r for r in earlier if r not in plain), *history[-1:]):
        url = f"{repository}/releases/tag/{release.tag}"
        yield release.day, _get_when(release.day), release.tag, release.title, url


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


def _gen_work_items(
    data: PlanningData, snapshot: Snapshot, focus: str, *entries: _Entry
) -> Iterator[dict[str, object]]:
    """
    Generates a planning phase's work items from its work entries.

    Each item takes its status from the planning data, the focus slice and the next
    slices count as next up, and an item with a Markdown home also links to its
    paragraph and names where it sits.
    """
    upcoming = frozenset((*data.next_slices, focus))

    for ref, key, label, tag in entries:
        found = _WORK_STATUSES.get(data.get_status(ref), "planned")
        section = data.sections.get(ref)

        if section is None:
            home: dict[str, str] = {}
        else:
            place = section.heading if section.owner is None else section.owner
            parts = (section.doc, place, section.id)
            home = {
                "planUrl": build_plan_url(snapshot, section),
                "location": " › ".join(gen_non_null(parts)),
            }

        yield {
            "id": _normalize_id(key),
            **({} if tag is None else {"tag": tag}),
            "title": label,
            "status": "next_up" if ref in upcoming else found,
            "body": _get_detail(data, ref),
            **home,
        }


def _build_dependency(
    data: PlanningData, node: Node, shown: AbstractSet[str]
) -> dict[str, object]:
    """
    Builds what a planning phase unlocks, keeping only refs the view shows.

    A ref reached through a real dependency and a chosen order counts as a real
    dependency.
    """
    unlocks = [
        (container, unlock)
        for unlock in data.get_unlocks(node.id)
        if (container := unlock.ref.partition(".")[0]) != node.id and container in shown
    ]
    kinds: dict[str, EdgeKind] = {
        **{container: unlock.kind for container, unlock in unlocks},
        **{c: u.kind for c, u in unlocks if u.kind == "blocked_by"},
    }
    reasons = list(
        dict.fromkeys(
            title
            for _, u in unlocks
            if u.reason is not None and (title := u.reason.title) is not None
        )
    )

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
    }


def _get_container(data: PlanningData, ref: str) -> str:
    """Gets the container a slice or decision ref belongs to, or any other ref."""
    item = data.slices.get(ref)
    found = data.decisions.get(ref) if item is None else item
    return ref if found is None else found.container


def _build_condensation(
    graph: nx.DiGraph[str],
) -> tuple[nx.DiGraph[int], dict[str, int]]:
    """Builds a graph's acyclic condensation, with each node's component index."""
    groups = [set(group) for group in nx.strongly_connected_components(graph)]
    members = {ref: index for index, group in enumerate(groups) for ref in group}
    return nx.condensation(graph, scc=groups), members


def _place(graph: nx.DiGraph[str], order: Sequence[str]) -> dict[str, _Placement]:
    """
    Places each node of a dependency graph in a grid cell, row by row in ``order``.

    A node's row is the longest path to it from a root, shared around a cycle. Its
    column is the smallest of its placed parents' columns, else the first, moved right
    while that cell is taken. Its span runs over its own and its descendants' columns,
    so a parent centres over its children, and it is forked when one of its parents
    has another child.

    Examples:

        >>> import networkx as nx
        >>>
        >>> graph = nx.DiGraph([("a", "b"), ("a", "c")])
        >>> for ref, placement in _place(graph, "abc").items():
        ...     print(ref, *placement)
        a 0 0 (0, 1) False
        b 1 0 (0, 0) True
        c 1 1 (1, 1) True

    """
    condensed, members = _build_condensation(graph)
    generations = enumerate(nx.topological_generations(condensed))
    depths = {index: depth for depth, found in generations for index in found}
    rows = {ref: depths[members[ref]] for ref in order}
    columns: dict[str, int] = {}
    taken: set[tuple[int, int]] = set()

    for ref in sorted(order, key=rows.__getitem__):
        parents = (columns[p] for p in graph.predecessors(ref) if p in columns)
        column = min(parents, default=0)

        while (rows[ref], column) in taken:
            column += 1

        columns[ref] = column
        taken.add((rows[ref], column))

    spans = {
        ref: [columns[other] for other in (ref, *nx.descendants(graph, ref))]
        for ref in order
    }
    return {
        ref: _Placement(
            row=rows[ref],
            column=columns[ref],
            span=(min(spans[ref]), max(spans[ref])),
            forked=any(len(graph.succ[p]) > 1 for p in graph.predecessors(ref)),
        )
        for ref in order
    }


def _build_areas(
    data: PlanningData, *nodes: Node, **statuses: str
) -> tuple[nx.DiGraph[str], dict[str, dict[str, object]]]:
    """
    Builds the graph of areas, then each area's open planning phase cards.

    A card notes the open planning phases in other areas it really depends on, and an
    area lists the real dependencies between its own cards; a landed upstream, a done
    upstream slice, a settled decision, a chosen order, and an edge within one planning
    phase are left out.
    The area graph keeps each real dependency between areas that a longer chain of
    areas does not already imply, and none inside a cycle of areas.
    """
    owners = {n.id: n.id if n.area is None else n.area for n in nodes}
    areas = list(dict.fromkeys(owners.values()))
    links: nx.DiGraph[str] = nx.DiGraph()
    links.add_nodes_from(owners)
    links.add_edges_from(
        (upstream, downstream)
        for edge in data.blocking_edges
        if (upstream := _get_container(data, edge.upstream)) in owners
        and (downstream := _get_container(data, edge.downstream)) in owners
        and upstream != downstream
        and data.get_status(edge.upstream) not in {"complete", "settled"}
    )
    crossing: nx.DiGraph[str] = nx.DiGraph()
    crossing.add_nodes_from(areas)
    crossing.add_edges_from(
        (owners[u], owners[v]) for u, v in links.edges if owners[u] != owners[v]
    )
    condensed, members = _build_condensation(crossing)
    reduced = nx.transitive_reduction(condensed)
    drawn: nx.DiGraph[str] = nx.DiGraph()
    drawn.add_nodes_from(areas)
    drawn.add_edges_from(
        (u, v) for u, v in crossing.edges if reduced.has_edge(members[u], members[v])
    )
    groups = {area: [ref for ref in owners if owners[ref] == area] for area in areas}
    cells = {
        ref: placement
        for refs in groups.values()
        for ref, placement in _place(links.subgraph(refs), refs).items()
    }
    open_legs = {
        n.id: {
            data.get_leg(item.ref)
            for item in n.slices
            if item.id not in _EXITS
            and not item.deferred
            and data.get_status(item.ref) != "complete"
        }
        or {data.get_leg(n.id)}
        for n in nodes
    }
    cards = {
        ref: {
            "id": _normalize_id(ref),
            "ref": ref,
            "title": _get_title(data, ref),
            "status": statuses[ref],
            "milestones": sorted(gen_non_null(open_legs[ref]), key=data.order.index),
            "needs": sorted(
                (u for u in links.predecessors(ref) if owners[u] != owners[ref]),
                key=data.order.index,
            ),
            "row": cells[ref].row,
            "column": cells[ref].column,
            "span": list(cells[ref].span),
            "forked": cells[ref].forked,
        }
        for ref in owners
    }

    return drawn, {
        area: {
            "id": _normalize_id(area),
            "title": _get_title(data, area),
            "cards": [cards[ref] for ref in refs],
            "edges": _build_edges(links.subgraph(refs).edges),
        }
        for area, refs in groups.items()
    }


def _place_shelf(graph: nx.DiGraph[str], order: Sequence[str]) -> dict[str, _Cell]:
    """
    Places a plan's slices: each row by depth, each column under the slice's parents.

    A depth-first walk from the roots, in ``order``, gives each leaf the next column. A
    child several parents lead to waits for the last of them and goes first among its
    siblings; the others sit with the child that has the most descendants in the
    middle. A parent takes the middle column of the children only it leads to, else of
    all its children.

    Examples:

        >>> import networkx as nx
        >>>
        >>> graph = nx.DiGraph([("a", "b"), ("a", "c"), ("c", "d"), ("a", "e")])
        >>> for ref, cell in _place_shelf(graph, "abcde").items():
        ...     print(ref, *cell)
        a 0 1
        b 1 0
        c 1 1
        d 2 1
        e 1 2

    """
    rows = {ref: placement.row for ref, placement in _place(graph, order).items()}
    sizes = {ref: len(nx.descendants(graph, ref)) for ref in order}
    columns: dict[str, int] = {}
    entered: set[str] = set()
    slots = count()

    def visit(ref: str) -> None:
        entered.add(ref)
        ready = sorted(
            (
                child
                for child in graph.successors(ref)
                if child not in columns
                and entered.issuperset(graph.predecessors(child))
            ),
            key=order.index,
        )
        ranked = sorted(
            (child for child in ready if graph.in_degree(child) == 1),
            key=lambda child: -sizes[child],
        )
        arranged: deque[str] = deque()

        for index, child in enumerate(ranked):
            (arranged.appendleft if index % 2 else arranged.append)(child)

        for child in [*(c for c in ready if graph.in_degree(c) > 1), *arranged]:
            visit(child)

        children = list(graph.successors(ref))
        owned = [columns[c] for c in children if graph.in_degree(c) == 1]
        under = sorted(owned or [columns[c] for c in children if c in columns])
        columns[ref] = under[(len(under) - 1) // 2] if under else next(slots)

    for root in (ref for ref in order if graph.in_degree(ref) == 0):
        visit(root)

    return {ref: _Cell(rows[ref], columns[ref]) for ref in order}


def _gen_shelf_plans(
    data: PlanningData, snapshot: Snapshot
) -> Iterator[dict[str, object]]:
    """
    Generates the plans shelf: each plan file with slices that ride no planning phase.

    A slice that lands with a planning phase already shows in that phase's work, so a
    plan whose slices all do is left off. Each slice notes its status, the open
    decisions and unfinished work it still waits on (a slice of its own plan by label),
    and its cell in a grid laid out from the plan's own ``blocked_by`` edges.
    """
    plans = gen_instances(data.containers.values(), PlanFile)
    shelved = [
        (plan, refs)
        for plan in sorted(plans, key=lambda item: item.id)
        if (refs := [item.ref for item in plan.slices if not item.lands_with])
    ]

    for plan, refs in shelved:
        graph: nx.DiGraph[str] = nx.DiGraph()
        graph.add_nodes_from(refs)
        graph.add_edges_from(
            (edge.upstream, edge.downstream)
            for edge in data.blocking_edges
            if edge.upstream in graph and edge.downstream in graph
        )
        cells = _place_shelf(graph, refs)
        waiting = {ref: data.get_waiting(ref) for ref in refs}
        labels = {ref: ref.partition(".")[2] or ref for ref in refs}
        heading = data.docs.get(f"{plan.id}.md", "").partition("\n")[0]
        title = heading.removeprefix("# ").removesuffix(" gameplan") or plan.id
        path = (GAMEPLANS_DIR / f"{plan.id}.md").relative_to(ROOT_DIR).as_posix()
        sections = {ref: data.sections.get(ref) for ref in refs}
        yield {
            "id": _normalize_id(plan.id),
            "title": title,
            "planUrl": f"{snapshot.repository}/blob/{snapshot.commit}/{path}",
            "slices": [
                {
                    "id": _normalize_id(ref),
                    "label": labels[ref],
                    "title": _get_title(data, ref),
                    "status": _WORK_STATUSES.get(
                        data.get_status(ref), "waiting" if waiting[ref] else "ready"
                    ),
                    "needs": [labels.get(need, need) for need in waiting[ref]],
                    **(
                        {}
                        if (section := sections[ref]) is None
                        else {"planUrl": build_plan_url(snapshot, section)}
                    ),
                    "row": cells[ref].row,
                    "column": cells[ref].column,
                }
                for ref in refs
            ],
            "edges": _build_edges(graph.edges),
        }


def _gen_prerequisites(
    data: PlanningData, node: Node, focus: str, **statuses: str
) -> Iterator[dict[str, object]]:
    """
    Generates a milestone's prerequisites in order, each with its Markdown reason.

    A prerequisite that is a planning phase the view shows takes that phase's status;
    any other counts as next up while it is in progress, in design, the focus slice, or
    one of the next slices. A prerequisite in an open planning phase names that phase's
    card. The reason is its prose, or its title while it has none.
    """
    upcoming = frozenset((*data.next_slices, focus))

    for ref in node.blocked_by:
        reason = data.reasons.get((node.id, ref))
        parts = () if reason is None else (reason.detail, reason.title)
        detail = next((part for part in parts if part is not None and part != ""), "")
        found = _PREREQUISITE_STATUSES.get(data.get_status(ref), "pending")
        guessed = "next_up" if ref in upcoming and found != "landed" else found
        shown = statuses.get(ref)
        phase = _get_container(data, ref)
        is_open = statuses.get(phase, "landed") != "landed"
        card = {"card": _normalize_id(phase)} if is_open else {}
        yield {
            "ref": ref,
            "title": _get_title(data, ref),
            "status": guessed if shown is None else shown,
            "detail": detail,
            **card,
        }


def build_forward_track(
    data: PlanningData,
    snapshot: Snapshot,
    page: Mapping[str, object],
    history: Sequence[Release],
) -> dict[str, object]:
    """
    Builds the forward-track view of the planning data.

    The focus is the first ready slice that belongs to a main-track planning phase,
    with that planning phase's first open decision when it has one. Each open planning
    phase is a card in its area's grid, and the history runs newest first.

    Args:

        data: The planning data.
        snapshot: The commit the links point at, with its unreleased version.
        page: The page copy.
        history: The tagged releases, oldest first.

    Returns:

        The ``snapshot``, ``page``, ``focus``, ``phases``, ``milestones``,
        ``history``, ``areas``, ``areaEdges``, and ``plans`` of the view.

    Raises:

        ValueError: If no ready slice belongs to a main-track planning phase.

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
        >>> track["focus"]["phase"], track["areas"][0]["cards"][0]["milestones"]
        ('R90', ['M90'])

    """
    nodes = [n for ref in data.order if isinstance(n := data.containers.get(ref), Node)]
    phases = [n for n in nodes if n.kind == "phase" and _PHASE.fullmatch(n.id)]
    milestones = [
        n for n in nodes if n.kind == "milestone" and _MILESTONE.fullmatch(n.id)
    ]
    accepted = [n for n in milestones if not n.proposed]
    finals = [n for n in accepted if data.get_leg(n.id) is None]
    shown = {n.id for n in [*phases, *milestones]}
    candidates = (
        ref
        for ref in data.ready_slices
        if _PHASE.fullmatch(data.slices[ref].container)
        and data.slices[ref].container in shown
    )
    focus = next(candidates, None)

    if focus is None:
        raise ValueError("no ready slice belongs to a main-track planning phase")

    owner = data.slices[focus].container
    legs = (data.get_leg(focus), data.get_leg(owner), finals[-1].id if finals else None)
    open_decisions = (
        ref
        for ref, item in data.decisions.items()
        if item.container == owner and item.settled is None
    )
    decision = next(open_decisions, None)
    landed = {n.id: "landed" for n in phases if data.get_status(n.id) == "complete"}
    current = {n.id: "next_up" for n in phases if n.id == owner}
    statuses = {**{n.id: "pending" for n in phases}, **current, **landed}
    repository = snapshot.repository.rstrip("/")
    releases = _gen_release_events(repository, *history)
    landings = (
        (landed_on, _get_when(landed_on), n.id, _get_title(data, n.id), None)
        for n in phases
        if (landed_on := data.get_landed(n.id)) is not None
    )
    ranked = sorted(
        enumerate([*releases, *landings]),
        key=lambda pair: (pair[1][0], pair[0]),
        reverse=True,
    )
    events = [event for _, event in ranked]
    not_landed = (n for n in phases if statuses[n.id] != "landed")
    drawn, areas = _build_areas(data, *not_landed, **statuses)
    boxes = _place(drawn, list(areas))
    entries = {n.id: list(_gen_work_entries(data, n)) for n in phases}
    exits = {
        ref for ref, found in entries.items() if {e[1] for e in found}.issubset(_EXITS)
    }

    if decision is None:
        open_decision: dict[str, dict[str, str]] = {}
    else:
        heading, body = _get_title(data, decision), _get_detail(data, decision)
        open_decision = {"decision": {"heading": heading, "body": body}}

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
            "milestone": next(gen_non_null(legs), None),
            "heading": _get_title(data, focus),
            "summary": _get_detail(data, focus),
            **open_decision,
        },
        "phases": [
            {
                "id": n.id,
                "title": _get_title(data, n.id),
                "purpose": _get_detail(data, n.id),
                "status": statuses[n.id],
                "planUrl": _get_plan_url(data, snapshot, n),
                "dependency": _build_dependency(data, n, shown),
                "workKind": "implementation" if n.id in exits else "slices",
                "work": list(_gen_work_items(data, snapshot, focus, *entries[n.id])),
            }
            for n in phases
        ],
        "milestones": [
            {
                "id": n.id,
                "title": _get_title(data, n.id),
                "summary": _get_detail(data, n.id),
                "prerequisites": list(_gen_prerequisites(data, n, focus, **statuses)),
                "planUrl": _get_plan_url(data, snapshot, n),
                **({} if n.landed is None else {"date": n.landed.isoformat()}),
            }
            for n in accepted
        ],
        "history": [
            {
                "when": when,
                "badge": badge,
                "title": title,
                **({} if url is None else {"url": url}),
            }
            for _, when, badge, title, url in events
        ],
        "areas": [
            {**area, "row": boxes[key].row, "column": boxes[key].column}
            for key, area in areas.items()
        ],
        "areaEdges": _build_edges(drawn.edges),
        "plans": list(_gen_shelf_plans(data, snapshot)),
    }


def _get_records(record: _Record, key: str) -> list[_Record]:
    """Gets a view record's list of records under ``key``."""
    values = require_listlike(record.get(key, ()), key, error=ValueError)
    return [require_mapping(value, key, error=ValueError) for value in values]


def _get_text(record: _Record, key: str) -> str:
    """Gets a view record's text under ``key``."""
    return require_instance(str, record.get(key), key, error=ValueError)


def _gen_duplicates(kind: str, *ids: str) -> Iterator[str]:
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
    milestones = _get_records(doc, "milestones")
    focus = require_mapping(doc.get("focus", {}), "focus", error=ValueError)
    areas = _get_records(doc, "areas")
    cards = [card for area in areas for card in _get_records(area, "cards")]
    phase_ids = [_get_text(phase, "id") for phase in phases]
    milestone_ids = [_get_text(item, "id") for item in milestones]
    area_ids = [_get_text(area, "id") for area in areas]
    card_ids = [_get_text(card, "id") for card in cards]
    card_refs = {_get_text(card, "ref") for card in cards}
    next_up = [_get_text(p, "id") for p in phases if p.get("status") == "next_up"]
    focus_phase, focus_milestone = focus.get("phase"), focus.get("milestone")
    needs = [
        (_get_text(card, "ref"), need)
        for card in cards
        for need in require_listlike(card.get("needs", ()), "needs", error=ValueError)
    ]
    named = [
        (_get_text(item, "id"), prerequisite.get("card"))
        for item in milestones
        for prerequisite in _get_records(item, "prerequisites")
    ]
    ends = [
        _get_text(edge, key)
        for edge in _get_records(doc, "areaEdges")
        for key in ("upstream", "downstream")
    ]
    plans = _get_records(doc, "plans")
    shelved = {
        _get_text(plan, "id"): [
            _get_text(s, "id") for s in _get_records(plan, "slices")
        ]
        for plan in plans
    }
    plan_ends = [
        (plan_id, _get_text(edge, key))
        for plan, plan_id in zip(plans, shelved, strict=True)
        for edge in _get_records(plan, "edges")
        for key in ("upstream", "downstream")
    ]
    yield from _gen_duplicates("node", *phase_ids, *milestone_ids)
    yield from _gen_duplicates("area", *area_ids, *shelved)
    yield from _gen_duplicates(
        "card", *card_ids, *chain.from_iterable(shelved.values())
    )

    for phase, phase_id in zip(phases, phase_ids, strict=True):
        work = (_get_text(item, "id") for item in _get_records(phase, "work"))
        yield from _gen_duplicates(f"phase {phase_id} work", *work)

    if focus_phase not in phase_ids:
        yield f"focus phase {focus_phase} names no phase"
    elif next_up != [focus_phase]:
        yield f"next-up phases {next_up} are not the focus phase {focus_phase} alone"

    if focus_milestone not in milestone_ids:
        yield f"focus milestone {focus_milestone} names no milestone"

    yield from (
        f"card {ref} needs unknown card {need}"
        for ref, need in needs
        if need not in card_refs
    )
    yield from (
        f"milestone {milestone} names unknown card {card}"
        for milestone, card in named
        if card is not None and card not in card_ids
    )
    yield from (
        f"area edge names unknown area {end}" for end in ends if end not in area_ids
    )
    yield from (
        f"plan {plan_id} edge names unknown slice {end}"
        for plan_id, end in plan_ends
        if end not in shelved[plan_id]
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


def build_forward_track_page(doc: _Record) -> str:
    """
    Builds the forward-track page from a forward-track view.

    The page inlines its style sheet and script and leaves out the document wrapper
    (``<html>``, ``<head>``, and ``<body>``), which the page's host supplies.

    Args:

        doc: A forward-track view that passes its schema and cross-reference checks.

    Returns:

        The page's HTML, starting with its ``<title>``.

    Examples:

        >>> from datetime import date
        >>> from riko.cli._gen_planning import Snapshot
        >>> from riko.cli._planning import PlanningData
        >>>
        >>> milestones = {"M90": {"blocked_by": ["R90"]}}
        >>> plan = {"phases": {"R90": {"area": "core"}}, "milestones": milestones}
        >>> data = PlanningData.from_documents({"plan": plan}, {})
        >>> snapshot = Snapshot("main", "abc1234", date(2026, 1, 1), "https://host/repo")
        >>> keys = ("title", "subtitle", "historyCaption", "outlook")
        >>> page = {**dict.fromkeys(keys, ""), "documentTitle": "Track"}
        >>> track = build_forward_track(data, snapshot, page, [])
        >>> build_forward_track_page(track).startswith("<title>Track</title>")
        True

    """
    env = Environment(
        loader=FileSystemLoader(VIEW_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["zip"] = zip
    env.filters["when"] = lambda text: _get_when(date.fromisoformat(text))
    css = (VIEW_DIR / "style.css").read_text()
    js = (VIEW_DIR / "controls.js").read_text()
    return env.get_template("index.html.j2").render(**doc, css=css, js=js)


def _load_forward_track() -> tuple[dict[str, object], list[str]]:
    """Loads the forward-track view for the current commit, with its problems."""
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

    return doc, problems


def main(html: bool = False) -> int:
    """
    Prints the forward-track view of the planning data for the current commit.

    The view is printed even when it breaks its schema or a cross-reference check;
    the problems go to standard error and the exit status is 1. With ``html``, the
    view is written as the forward-track page instead and its path printed, but only
    when it has no problems.

    Kwargs:

        html: Whether to write the page rather than print the view.

    Returns:

        The exit status: 1 when the view has a problem, else 0.

    """
    doc, problems = _load_forward_track()

    for problem in problems:
        print(problem, file=sys.stderr)

    if not html:
        print(json.dumps(doc, indent=2))
    elif not problems:
        HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        HTML_PATH.write_text(build_forward_track_page(doc))
        print(HTML_PATH)

    return 1 if problems else 0


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate the forward-track view.")
    parser.add_argument(
        "--html", action="store_true", help="write the view as a self-contained page"
    )
    raise SystemExit(main(html=parser.parse_args().html))
