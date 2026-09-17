# vim: sw=4:ts=4:expandtab

"""Release-management helpers for the manage CLI."""

import re
import shutil
from collections.abc import Iterable, Iterator
from functools import partial
from os import environ
from pathlib import Path
from subprocess import CalledProcessError, check_call, check_output
from sys import exit
from typing import NamedTuple

import click
import requests
from click import Choice

from riko.base._paths import ROOT_DIR

_CHANGELOG_PATH = ROOT_DIR / "docs" / "CHANGES.rst"
_GITHUB_REPO = "nerevu/riko"
_PYPI_PROJECT = "riko"

_RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_RELEASE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_RST_SUBHEADING_RE = re.compile(r"^(?P<title>[^\n]+)\n~+$", re.MULTILINE)
_RELEASE_SECTION_RE = re.compile(
    r"^(?P<version>v\d+\.\d+\.\d+) \((?P<release_date>[^)]+)\)\n-+\n\n"
    r"(?P<body>.*?)"
    r"(?=^v\d+\.\d+\.\d+ \([^)]+\)\n-+\n|\Z)",
    re.MULTILINE | re.DOTALL,
)

_gh: str | None = shutil.which("gh")


class _Entry(NamedTuple):
    version: str
    release_date: str
    body: str


def _gen_changelog_entries(path: Path = _CHANGELOG_PATH) -> Iterator[_Entry]:
    """Emit changelog entries in document order."""
    text = path.read_text(encoding="utf-8")

    for match in _RELEASE_SECTION_RE.finditer(text):
        yield _Entry(match["version"], match["release_date"], match["body"].strip())


def _get_changelog_entry(
    version: str | None = None, path: Path = _CHANGELOG_PATH
) -> _Entry:
    """Select a changelog version, release date, and RST body."""
    for entry in _gen_changelog_entries(path):
        if (version is None) or entry.version == version:
            return entry

    if version:
        msg = f"No changelog entry found for {version} in {path}"
    else:
        msg = f"No release section found in {path}"

    raise RuntimeError(msg)


def _validate_tag(version: str, *expected: str) -> None:
    """Validate a release version and optional expected tag."""
    if not _RELEASE_TAG_RE.fullmatch(version):
        raise RuntimeError(f"Invalid release tag {version!r}")

    if expected and version not in expected:
        raise RuntimeError(f"{version=} does not exist in {expected=}")


def _gen_gh_tags(releases: bool = False) -> Iterator[str]:
    """Emit remote tags."""
    if not _gh:
        raise RuntimeError("gh not found")

    param, field = ("releases", "tag_name") if releases else ("tags", "name")
    url = f"repos/{_GITHUB_REPO}/{param}?per_page=100"
    args = [_gh, "api", "--paginate", "--jq", f".[].{field}", url]
    output = check_output(args, text=True)

    for tag in output.splitlines():
        if _RELEASE_TAG_RE.fullmatch(tag):
            yield tag


def _gen_pypi_tags() -> Iterator[str]:
    """Emit versions already published to PyPI as release tags."""
    url = f"https://pypi.org/pypi/{_PYPI_PROJECT}/json"
    response = requests.get(url, timeout=15)

    if response.ok:
        for tag in response.json()["releases"]:
            if _RELEASE_VERSION_RE.fullmatch(tag):
                yield f"v{tag}"


def _gen_missing_versions(published: Iterable[str]) -> Iterator[str]:
    """Emit remote release tags absent from a publication target."""
    missing = set(_gen_gh_tags()).difference(published)
    release_key = lambda version: tuple(map(int, version.removeprefix("v").split(".")))
    yield from sorted(missing, key=release_key)


def _dispatch_workflow(
    workflow: str, dry_run: bool = False, **fields: str | bool
) -> None:
    """Dispatch a workflow from the current main branch."""
    if not _gh:
        raise RuntimeError("gh not found")

    args = [_gh, "workflow", "run", workflow, "--repo", _GITHUB_REPO, "--ref", "main"]

    for key, value in fields.items():
        rendered = str(value).lower() if isinstance(value, bool) else value
        args.extend(["-f", f"{key}={rendered}"])

    if dry_run:
        click.echo(f"[dry-run] would dispatch: {' '.join(args)}")
    else:
        check_call(args)


def _backfill_github(
    version: str, notes_only: bool = False, dry_run: bool = False
) -> None:
    """Dispatch GitHub release creation or release-note repair."""
    _validate_tag(version, *_gen_gh_tags())
    entry = _get_changelog_entry(version)

    if entry.release_date == "Unreleased":
        raise RuntimeError(f"Changelog entry for {version} is unreleased")

    exists = version in set(_gen_gh_tags(releases=True))
    msg = f"GitHub release {version}"

    if notes_only and not exists:
        msg += " does not exist. Run without --notes-only to create it"
        raise RuntimeError(msg)
    elif not notes_only and exists:
        msg += " already exists. Use --notes-only to replace its notes"
        raise RuntimeError(msg)

    _dispatch_workflow(
        "release.yml", dry_run=dry_run, tag=version, notes_only=notes_only
    )


def _backfill_pypi(version: str, dry_run: bool = False) -> None:
    """Dispatch publication of an existing tag to PyPI."""
    _validate_tag(version, *_gen_gh_tags())

    if version in set(_gen_pypi_tags()):
        raise RuntimeError(f"{_PYPI_PROJECT} {version} already exists on PyPI")

    _dispatch_workflow("publish.yml", dry_run=dry_run, tag=version)


@click.command(name="release-notes")
@click.argument("version", required=False)
def _release_notes_command(version: str | None = None) -> None:
    """Convert a changelog section to Markdown release notes."""
    entry = _get_changelog_entry(version)

    if environ.get("GITHUB_REF_TYPE") == "tag":
        _validate_tag(entry.version, environ.get("GITHUB_REF_NAME", ""))

    if environ.get("GITHUB_ACTIONS") and entry.release_date == "Unreleased":
        raise RuntimeError(f"Changelog entry for {entry.version} is unreleased")

    click.echo(_RST_SUBHEADING_RE.sub(r"### \g<title>", entry.body))


@click.command(name="missing")
@click.argument(
    "targets", nargs=-1, type=Choice(["github", "pypi"], case_sensitive=False)
)
def _missing_command(targets: tuple[str, ...] = ()) -> None:
    """List release versions missing from publication targets."""
    targets = targets or ("github", "pypi")
    missing_by_target = {"github": partial(_gen_gh_tags, True), "pypi": _gen_pypi_tags}
    multiple = len(targets) > 1

    for target in targets:
        tags = missing_by_target[target]()
        versions = _gen_missing_versions(tags)

        if multiple:
            click.echo(f"{target}:")

        for version in versions:
            click.echo(version)


@click.command(name="backfill")
@click.argument("target", type=Choice(["github", "pypi"], case_sensitive=False))
@click.argument("version")
@click.option(
    "--notes-only", help="Replace notes on an existing GitHub release", is_flag=True
)
@click.option(
    "-d",
    "--dry-run",
    help="Show the workflow dispatch without triggering it",
    is_flag=True,
)
def _backfill_command(
    target: str, version: str, notes_only: bool = False, dry_run: bool = False
) -> None:
    """Backfill an incomplete historical release."""
    is_github = target == "github"

    if notes_only and not is_github:
        raise click.UsageError("--notes-only is only valid for GitHub releases")

    try:
        if is_github:
            _backfill_github(version, notes_only, dry_run)
        else:
            _backfill_pypi(version, dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


RELEASE_NOTES_COMMAND = _release_notes_command
MISSING_COMMAND = _missing_command
BACKFILL_COMMAND = _backfill_command
