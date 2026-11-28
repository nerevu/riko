# vim: sw=4:ts=4:expandtab
"""
Generates the planning tables and dependency graph from the planning data.

Each ``planning-`` block in a planning document is rebuilt from the TOML facts and
the titles in their Markdown homes. Run as a module with ``--json`` to print the whole
model, linked to the current commit, instead of rewriting any document.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from argparse import ArgumentParser
from datetime import date
from functools import partial
from itertools import chain
from os.path import relpath
from pathlib import PurePosixPath
from posixpath import normpath
from shutil import which
from subprocess import run
from typing import TYPE_CHECKING, NamedTuple

from riko.base._guards import require_mapping
from riko.base._iterutils import gen_instances
from riko.base._paths import (
    DOCS_DIR,
    GAMEPLANS_DIR,
    PYPROJECT,
    ROOT_DIR,
    SEQUENCE_PATH,
    TRACKER_PATH,
)
from riko.base._require_guards import require_instance
from riko.base._strutils import get_codegen_note

from ._gen_blocks import (
    build_block_pattern,
    build_marker_pattern,
    build_md_table,
    gen_block_offenders,
    generate_blocks,
)
from ._planning import Lane, Node, PlanFile, load_planning

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from ._planning import EdgeKind, PlanningData, Section

type _Collapsed = tuple[str, EdgeKind, Section | None]

_CHANGES_PATH = DOCS_DIR / "CHANGES.rst"
_NOTE = get_codegen_note("--planning")
_PREFIX = "planning-"
_MILESTONE_TRACK = "R"
_PLANS_PATH = GAMEPLANS_DIR.relative_to(ROOT_DIR).as_posix()
_UNSAFE = re.compile(r"[^A-Za-z0-9_]")
_UNRELEASED = re.compile(r"^(?P<version>v\S+) \(Unreleased\)$", re.MULTILINE)
_ARROWS: dict[EdgeKind, str] = {"blocked_by": "-->", "scheduled_after": "-.->"}

_WORDS: dict[str, str] = {
    "planned": "Planned",
    "in_design": "In design",
    "in_progress": "In progress",
    "complete": "Complete",
    "deferred": "Deferred",
    "open": "Open",
    "settled": "Settled",
}

_CLASS_DEFS = (
    "classDef planned fill:#ffffff,stroke:#8c959f",
    "classDef in_design fill:#fff8c5,stroke:#9a6700",
    "classDef in_progress fill:#ddf4ff,stroke:#0969da",
    "classDef complete fill:#dafbe1,stroke:#1a7f37",
    "classDef deferred fill:#f6f8fa,stroke:#d0d7de",
    "classDef proposed stroke-dasharray:5 5",
)

PLANNING_DOCS: dict[Path, frozenset[str]] = {
    TRACKER_PATH: frozenset({"track-r", "track-p"}),
    SEQUENCE_PATH: frozenset({"graph", "next", "lanes", "decisions"}),
    GAMEPLANS_DIR / "agent-scenarios.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "agents.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "ai-inference.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "cli.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "connectors.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "database-transforms.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "feed-native-streaming.md": frozenset({"slices"}),
    GAMEPLANS_DIR / "mcp.md": frozenset({"slices"}),
}

PLANNING_PATTERN = build_block_pattern(
    chain.from_iterable(PLANNING_DOCS.values()), prefix=_PREFIX
)
PLANNING_MARKERS = build_marker_pattern(_PREFIX)


class Snapshot(NamedTuple):
    """
    The commit an export describes.

    Attributes:

        branch: The checked-out branch.
        commit: The ``HEAD`` commit hash its links point at.
        today: The export date.
        repository: The repository's web URL.
        version: The unreleased version the changelog is collecting, when known.

    """

    branch: str
    commit: str
    today: date
    repository: str
    version: str | None = None


def _escape(text: str) -> str:
    """Escapes a table cell's pipes."""
    return text.replace("|", r"\|")


def _get_label(data: PlanningData, ref: str, shown: str | None = None) -> str:
    """Gets a ref's ``id · title`` label, or only its id while it has no title."""
    section = data.sections.get(ref)
    name = ref if shown is None else shown
    title = None if section is None else section.title
    return name if title is None else f"{name} · {title}"


def _link(data: PlanningData, ref: str, doc: str, shown: str | None = None) -> str:
    """Gets a ref's label linked to its Markdown home, relative to ``doc``."""
    section = data.sections.get(ref)
    label = _escape(_get_label(data, ref, shown))

    if section is None:
        href = ""
    elif normpath(section.doc) == normpath(doc):
        href = f"#{section.anchor}" if section.anchor else ""
    else:
        start = (GAMEPLANS_DIR / doc).parent
        path = PurePosixPath(relpath(GAMEPLANS_DIR / section.doc, start)).as_posix()
        href = f"{path}#{section.anchor}" if section.anchor else path

    return f"[{label}]({href})" if href else label


def _get_word(data: PlanningData, ref: str) -> str:
    """Gets a ref's status in plain words."""
    return _WORDS[data.get_status(ref)]


def _get_day(day: date | None) -> str:
    """Gets a date in ISO form, or blank."""
    return "" if day is None else day.isoformat()


def _get_nodes(data: PlanningData) -> list[Node]:
    """Gets the planning phases and milestones in work order."""
    found = (data.containers.get(ref) for ref in data.order)
    return [node for node in found if isinstance(node, Node)]


def _collapse_unlocks(data: PlanningData, ref: str) -> list[_Collapsed]:
    """
    Gets the other containers a ref unlocks, in work order.

    A container unlocked through more than one edge is a real dependency when any edge
    is, and keeps the first reason found.
    """
    own = ref.partition(".")[0]
    kinds: dict[str, EdgeKind] = {}
    reasons: dict[str, Section] = {}

    for unlock in data.get_unlocks(ref):
        container = unlock.ref.partition(".")[0]

        if container != own and kinds.get(container) != "blocked_by":
            kinds[container] = unlock.kind

        if container != own and unlock.reason is not None:
            reasons.setdefault(container, unlock.reason)

    ordered = sorted(kinds, key=data.order.index)
    return [
        (container, kinds[container], reasons.get(container)) for container in ordered
    ]


def _render_track(data: PlanningData, doc: str, track: str) -> str:
    """Renders one track's planning phases, then its milestones, as a table."""
    nodes = _get_nodes(data)
    phases = [node for node in nodes if node.kind == "phase" and node.track == track]
    milestones = [
        node for node in nodes if node.kind == "milestone" and track == _MILESTONE_TRACK
    ]
    rows = [("Phase", "Status", "Landed", "Unlocks")]

    for node in chain(phases, milestones):
        unlocks: list[str] = []

        for container, kind, reason in _collapse_unlocks(data, node.id):
            name = f"before {container}" if kind == "scheduled_after" else container
            badge = None if reason is None else reason.title
            unlocks.append(name if badge is None else f"{name} ({badge})")

        label = _link(data, node.id, doc)
        rows.append(
            (
                f"{label} (proposed)" if node.proposed else label,
                _get_word(data, node.id),
                _get_day(data.get_landed(node.id)),
                _escape(", ".join(unlocks)),
            )
        )

    return f"{build_md_table(rows)}\n"


def _quote(text: str) -> str:
    """Quotes a Mermaid label."""
    return f'"{text.replace('"', "#quot;")}"'


def _render_graph(data: PlanningData, doc: str) -> str:
    """
    Renders the planning phases and milestones as a Mermaid flowchart.

    Planning phases sit in one subgraph per area; a real dependency is a solid
    arrow and a chosen order a dotted one.
    """
    nodes = _get_nodes(data)
    ids = {node.id: f"n_{_UNSAFE.sub('_', node.id)}" for node in nodes}
    areas: dict[str | None, list[Node]] = {}
    lines = ["```mermaid", "flowchart TD"]

    for node in nodes:
        areas.setdefault(node.area if node.kind == "phase" else None, []).append(node)

    for area, members in sorted(areas.items(), key=lambda pair: pair[0] is None):
        defs = [f"{ids[n.id]}[{_quote(_get_label(data, n.id))}]" for n in members]

        if area is None:
            lines.extend(f"    {line}" for line in defs)
        else:
            section = data.sections.get(area)
            title = area if section is None or section.title is None else section.title
            lines.append(f"    subgraph a_{_UNSAFE.sub('_', area)}[{_quote(title)}]")
            lines.extend(f"        {line}" for line in defs)
            lines.append("    end")

    for node in nodes:
        for container, kind, _ in _collapse_unlocks(data, node.id):
            if container in ids:
                lines.append(f"    {ids[node.id]} {_ARROWS[kind]} {ids[container]}")

    lines.extend(f"    {class_def}" for class_def in _CLASS_DEFS)
    lines.extend(f"    class {ids[n.id]} {data.get_status(n.id)}" for n in nodes)
    lines.extend(f"    class {ids[n.id]} proposed" for n in nodes if n.proposed)
    lines.append("```")
    return "\n".join(lines) + "\n"


def _render_next(data: PlanningData, doc: str) -> str:
    """Renders the slices to work on next as a table."""
    rows = [("Slice", "Phase", "Status", "Waiting on")]
    rows.extend(
        (
            _link(data, ref, doc),
            _link(data, data.slices[ref].container, doc),
            _get_word(data, ref),
            ", ".join(data.get_waiting(ref)),
        )
        for ref in data.next_slices
    )
    return f"{build_md_table(rows)}\n"


def _render_lanes(data: PlanningData, doc: str) -> str:
    """Renders the housekeeping lanes as a table."""
    found = (data.containers.get(ref) for ref in data.order)
    rows = [("Lane", "Owner", "Trigger", "Lands with", "Status")]

    for lane in gen_instances(found, Lane):
        hosts = chain.from_iterable(item.lands_with for item in lane.slices)
        rows.append(
            (
                _link(data, lane.id, doc),
                "" if lane.owner is None else _escape(lane.owner),
                "" if lane.trigger is None else _escape(lane.trigger),
                ", ".join(dict.fromkeys(hosts)),
                _get_word(data, lane.id),
            )
        )

    return f"{build_md_table(rows)}\n"


def _render_decisions(data: PlanningData, doc: str) -> str:
    """Renders the decisions, open ones first, as a table."""
    decisions = sorted(
        data.decisions.values(),
        key=lambda item: (item.settled is not None, data.order.index(item.container)),
    )
    rows = [("Decision", "Phase", "Status", "Settled")]
    rows.extend(
        (
            _link(data, item.ref, doc),
            _link(data, item.container, doc),
            _WORDS[item.status],
            _get_day(item.settled),
        )
        for item in decisions
    )
    return f"{build_md_table(rows)}\n"


def _render_slices(data: PlanningData, doc: str) -> str:
    """Renders the slices of the plan whose own document is ``doc`` as a table."""
    plan = data.containers.get(PurePosixPath(doc).stem)
    slices = plan.slices if isinstance(plan, PlanFile) else ()
    rows = [("Slice", "Lands with", "Status")]
    rows.extend(
        (
            _link(data, item.ref, doc, item.id),
            ", ".join(item.lands_with),
            _get_word(data, item.ref),
        )
        for item in slices
    )
    return f"{build_md_table(rows)}\n"


_RENDERERS: dict[str, Callable[[PlanningData, str], str]] = {
    "track-r": partial(_render_track, track="R"),
    "track-p": partial(_render_track, track="P"),
    "graph": _render_graph,
    "next": _render_next,
    "lanes": _render_lanes,
    "decisions": _render_decisions,
    "slices": _render_slices,
}


def generate_planning_blocks(text: str, data: PlanningData, doc: str) -> str:
    """
    Generates a planning document's ``planning-`` blocks from the planning data.

    Args:

        text: The document holding the marked blocks.
        data: The planning data.
        doc: The document's path relative to the plans directory; links are relative
            to it.

    Returns:

        The document with each marked block regenerated.

    Examples:

        >>> from riko.cli._planning import PlanningData
        >>>
        >>> plan = {"lanes": {"tidy": {"owner": "user", "trigger": "weekly"}}}
        >>> data = PlanningData.from_documents({"plan": plan}, {})
        >>> text = "<!-- planning-lanes -->\\n<!-- /planning-lanes -->"
        >>> print(generate_planning_blocks(text, data, "plan.md").splitlines()[3])
        | tidy | user | weekly |  | Planned |

    """
    render = lambda key: _RENDERERS[key](data, doc)
    return generate_blocks(text, PLANNING_PATTERN, render, _NOTE, prefix=_PREFIX)


def gen_planning_offenders(data: PlanningData) -> Iterator[str]:
    """
    Finds planning blocks that are unknown, missing, or drift from the planning data.

    Args:

        data: The planning data.

    Yields:

        One message per offending document.

    """
    for path, keys in PLANNING_DOCS.items():
        doc = relpath(path, GAMEPLANS_DIR)
        regenerate = partial(generate_planning_blocks, data=data, doc=doc)
        yield from gen_block_offenders(
            path, PLANNING_PATTERN, keys, regenerate, "--planning", PLANNING_MARKERS
        )


def build_plan_url(snapshot: Snapshot, section: Section) -> str:
    """
    Builds a Markdown home's absolute link at the snapshot's commit.

    A heading links to its rendered anchor. A lead-in or exit bullet has no anchor of
    its own, so it links to its line in the file's source view; the commit pins the
    line.

    Args:

        snapshot: The commit the link points at.
        section: The Markdown home.

    Returns:

        The web URL of the home's file, with its line or anchor when it has one.

    Examples:

        >>> from datetime import date
        >>> from riko.cli._planning import Section
        >>>
        >>> snapshot = Snapshot("main", "abc", date(2026, 1, 1), "https://host/repo")
        >>> home = Section("lead_in", "X1.a", "plan.md", "x1-title", line=7)
        >>> build_plan_url(snapshot, home).rsplit("/", 1)[-1]
        'plan.md?plain=1#L7'

    """
    path = normpath(f"{_PLANS_PATH}/{section.doc}")

    if section.kind != "heading" and section.line is not None:
        suffix = f"?plain=1#L{section.line}"
    elif section.anchor:
        suffix = f"#{section.anchor}"
    else:
        suffix = ""

    return f"{snapshot.repository}/blob/{snapshot.commit}/{path}{suffix}"


def _describe(data: PlanningData, snapshot: Snapshot, ref: str) -> dict[str, object]:
    """Builds the fields every exported planning ref shares."""
    section = data.sections.get(ref)
    landed = data.get_landed(ref)
    unlocks = [
        {
            "ref": unlock.ref,
            "upstream": unlock.upstream,
            "kind": unlock.kind,
            "badge": None if unlock.reason is None else unlock.reason.title,
            "detail": None if unlock.reason is None else unlock.reason.detail,
        }
        for unlock in data.get_unlocks(ref)
    ]
    return {
        "ref": ref,
        "status": data.get_status(ref),
        "landed": None if landed is None else landed.isoformat(),
        "title": None if section is None else section.title,
        "summary": None if section is None else section.detail,
        "anchor": None if section is None else section.anchor,
        "doc": None if section is None else section.doc,
        "section": None if section is None else section.heading,
        "line": None if section is None else section.line,
        "plan_url": None if section is None else build_plan_url(snapshot, section),
        "unlocks": unlocks,
    }


def build_export(data: PlanningData, snapshot: Snapshot) -> dict[str, object]:
    """
    Builds the whole planning model as JSON-ready data.

    Args:

        data: The planning data.
        snapshot: The commit whose files the absolute links point at.

    Returns:

        The ``snapshot``, ``order``, ``next``, ``areas``, ``nodes``, ``slices``,
        ``decisions``, and ``lanes``, with every derived status, date, title,
        summary, anchor, location, link, and unlock.

    Examples:

        >>> from datetime import date
        >>> from riko.cli._planning import PlanningData
        >>>
        >>> data = PlanningData.from_documents({"plan": {"phases": {"X1": {}}}}, {})
        >>> snapshot = Snapshot("main", "abc", date(2026, 1, 1), "https://host/repo")
        >>> export = build_export(data, snapshot)
        >>> export["order"], export["nodes"][0]["status"]
        (['X1'], 'planned')

    """
    nodes = _get_nodes(data)
    areas = [key for key in data.sections if key in data.areas]
    lanes = list(gen_instances(data.containers.values(), Lane))
    titles = {key: data.sections[key].title for key in areas}
    return {
        "snapshot": {
            "branch": snapshot.branch,
            "commit": snapshot.commit,
            "date": snapshot.today.isoformat(),
            "repository": snapshot.repository,
        },
        "order": list(data.order),
        "next": list(data.next_slices),
        "areas": [
            {
                "id": key,
                "title": titles[key],
                "summary": data.sections[key].detail,
                "anchor": data.sections[key].anchor,
                "plan_url": build_plan_url(snapshot, data.sections[key]),
            }
            for key in areas
        ],
        "nodes": [
            {
                **_describe(data, snapshot, node.id),
                "kind": node.kind,
                "track": node.track,
                "area": node.area,
                "area_title": None if node.area is None else titles.get(node.area),
                "proposed": node.proposed,
                "blocked_by": list(node.blocked_by),
                "scheduled_after": list(node.scheduled_after),
                "leg": data.get_leg(node.id),
            }
            for node in nodes
        ],
        "slices": [
            {
                **_describe(data, snapshot, ref),
                "container": item.container,
                "id": item.id,
                "deferred": item.deferred,
                "lands_with": list(item.lands_with),
                "blocked_by": list(item.blocked_by),
                "scheduled_after": list(item.scheduled_after),
                "waiting_on": list(data.get_waiting(ref)),
            }
            for ref, item in data.slices.items()
        ],
        "decisions": [
            {
                **_describe(data, snapshot, ref),
                "container": item.container,
                "id": item.id,
                "settled": None if item.settled is None else item.settled.isoformat(),
            }
            for ref, item in data.decisions.items()
        ],
        "lanes": [
            {
                **_describe(data, snapshot, lane.id),
                "owner": lane.owner,
                "trigger": lane.trigger,
            }
            for lane in lanes
        ],
    }


def read_git(*args: str) -> str:
    """
    Reads one git command's output, run in the repository root.

    Args:

        args: The git arguments.

    Returns:

        The command's standard output, stripped.

    Raises:

        RuntimeError: If git is not installed.

    """
    git = which("git")

    if git is None:
        raise RuntimeError("git not found")

    result = run([git, *args], cwd=ROOT_DIR, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def load_snapshot() -> Snapshot:
    """
    Loads the checked-out commit, the repository URL, and the unreleased version.

    Returns:

        The snapshot of ``HEAD`` as of today.

    Raises:

        RuntimeError: If git is missing or ``pyproject.toml`` names no repository URL.

    """
    pyproject: Mapping[str, object] = tomllib.loads(PYPROJECT.read_text())
    project: Mapping[str, object] = require_mapping(
        pyproject.get("project"), "pyproject [project]", error=RuntimeError
    )
    urls: Mapping[str, object] = require_mapping(
        project.get("urls"), "pyproject [project.urls]", error=RuntimeError
    )
    repository = require_instance(
        str, urls.get("Repository"), "pyproject Repository URL", error=RuntimeError
    )
    unreleased = _UNRELEASED.search(_CHANGES_PATH.read_text())
    return Snapshot(
        branch=read_git("rev-parse", "--abbrev-ref", "HEAD"),
        commit=read_git("rev-parse", "HEAD"),
        today=date.today(),
        repository=repository,
        version=None if unreleased is None else unreleased["version"],
    )


def write_json() -> int:
    """
    Writes the planning model as JSON to standard output.

    Its links point at the ``HEAD`` commit, so a dirty working tree gets a warning on
    standard error.
    """
    snapshot = load_snapshot()

    if read_git("status", "--porcelain"):
        print("warning: uncommitted changes; links point at HEAD", file=sys.stderr)

    print(json.dumps(build_export(load_planning(), snapshot), indent=2))
    return 0


def main() -> int:
    """
    Regenerates the planning blocks present in each planning document.

    Nothing is written while the planning data has a problem other than an id whose
    Markdown home is not written yet; the problems are printed instead. Missing blocks
    are left for the documentation lint to report.
    """
    data = load_planning()
    today = date.today()
    problems = [p for p in data.gen_problems(today) if p.kind != "missing_home"]

    for problem in problems:
        print(problem)

    present = [path for path in PLANNING_DOCS if path.exists() and not problems]

    for path in present:
        text = path.read_text()
        generated = generate_planning_blocks(text, data, relpath(path, GAMEPLANS_DIR))

        if generated != text:
            path.write_text(generated)

    return 1 if problems else 0


if __name__ == "__main__":
    parser = ArgumentParser(description="Generate the planning blocks.")
    parser.add_argument(
        "--json", action="store_true", help="print the planning model as JSON"
    )
    raise SystemExit(write_json() if parser.parse_args().json else main())
