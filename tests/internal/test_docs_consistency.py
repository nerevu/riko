# vim: sw=4:ts=4:expandtab
"""
Tests documentation-consistency invariants.

Guards the ``_docs/`` model against the drift catalogued in the doc review: a
complete ``§0-27`` index, every active gameplan indexed, retired gameplans kept
out of the active listing, phase status confined to ``PHASE_CHECKLISTS.md``, and
completion claims not outrunning the packaged version. All checks are hard
asserts; the ownership-boundary and version cleanups that made the last two pass
have landed.
"""

import re
import tomllib
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCS = _REPO / "_docs"
_ROADMAP = _DOCS / "ROADMAP.md"
_TRACKER = _DOCS / "PHASE_CHECKLISTS.md"
_GAMEPLANS = _DOCS / "gameplans"
_PYPROJECT = _REPO / "pyproject.toml"

_EXPECTED_SECTIONS = 28

_STATUS_BANNER = re.compile(
    r"^\s*>?\s*\*\*status\b\s*(?::|\*\*)", re.IGNORECASE | re.MULTILINE
)
_SECTION_ROW = re.compile(r"^\|\s*(\d+)\s*\|", re.MULTILINE)
_GAMEPLAN_LINK = re.compile(r"gameplans/([A-Za-z0-9._-]+\.md)")
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_COMPLETION = re.compile(
    r"\b(complete|completed|delivered|shipped|landed|done)\b", re.IGNORECASE
)
_TARGET = re.compile(
    r"\b(target|targeted|planned|plan|next|prerequisite|prereq|future)\b",
    re.IGNORECASE,
)


def _read(path):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return text


def _gameplan_paths():
    paths = sorted(_GAMEPLANS.glob("*.md")) if _GAMEPLANS.exists() else []
    return paths


def _is_retired(text):
    retired = "retired" in text.split("\n", 1)[0].lower()
    return retired


def _version_tuple(text):
    match = _VERSION.search(text)
    parsed = tuple(int(part) for part in match.groups()) if match else (0, 0, 0)
    return parsed


def _packaged_version():
    data = tomllib.loads(_read(_PYPROJECT)) if _PYPROJECT.exists() else {}
    raw = data.get("project", {}).get("version", "0.0.0")
    return _version_tuple(raw)


def _table_rows(text, name):
    rows = [
        line
        for line in text.splitlines()
        if f"gameplans/{name}" in line and line.lstrip().startswith("|")
    ]
    return rows


def _status_banner_offenders():
    offenders = [
        path.name for path in _gameplan_paths() if _STATUS_BANNER.search(_read(path))
    ]
    return offenders


def _retired_listing_offenders():
    roadmap = _read(_ROADMAP)
    offenders = [
        path.name
        for path in _gameplan_paths()
        if _is_retired(_read(path))
        and _table_rows(roadmap, path.name)
        and not any("retired" in row.lower() for row in _table_rows(roadmap, path.name))
    ]
    return offenders


def _version_claim_offenders(current):
    offenders = [
        line.strip()
        for path in (_TRACKER, _ROADMAP)
        for line in _read(path).splitlines()
        if _VERSION.search(line)
        and _version_tuple(line) > current
        and _COMPLETION.search(line)
        and not _TARGET.search(line)
    ]
    return offenders


def test_section_index_is_complete():
    counts = Counter(int(n) for n in _SECTION_ROW.findall(_read(_ROADMAP)))
    assert counts == Counter(range(_EXPECTED_SECTIONS))


def test_all_active_gameplans_are_indexed():
    linked = set(_GAMEPLAN_LINK.findall(_read(_ROADMAP)))
    active = {path.name for path in _gameplan_paths() if not _is_retired(_read(path))}
    assert active <= linked, f"unindexed active gameplans: {sorted(active - linked)}"


def test_retired_gameplans_are_marked_retired():
    offenders = _retired_listing_offenders()
    assert not offenders, (
        f"retired gameplans listed without a Retired marker: {offenders}"
    )


def test_no_status_banner_in_gameplans():
    offenders = _status_banner_offenders()
    assert not offenders, f"status banners belong only in the tracker: {offenders}"


def test_no_completion_claim_above_packaged_version():
    offenders = _version_claim_offenders(_packaged_version())
    assert not offenders, f"completion claimed above packaged version: {offenders}"
