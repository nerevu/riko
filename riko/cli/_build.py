# vim: sw=4:ts=4:expandtab

"""Build and packaging helpers for the manage CLI."""

import shutil
from glob import glob
from os.path import getmtime
from subprocess import CalledProcessError, call, check_call
from sys import exit

import click

from riko.base._paths import ROOT_DIR

_uv: str | None = shutil.which("uv")
_twine: str | None = shutil.which("twine")


def _clean() -> None:
    """Remove Python file and build artifacts."""
    for name in ("dist", "build"):
        shutil.rmtree(ROOT_DIR / name, ignore_errors=True)

    for pattern in ("*.egg-info", "src/*.egg-info"):
        for path in glob(str(ROOT_DIR / pattern)):
            shutil.rmtree(path, ignore_errors=True)

    for pattern in ("*.pyc", "*.pyo", "*~"):
        for path in ROOT_DIR.rglob(pattern):
            path.unlink(missing_ok=True)


def _build() -> None:
    """Build the riko package."""
    if _uv:
        check_call([_uv, "build"])
    else:
        raise RuntimeError("uv not found")


def _publish(dry_run: bool = False) -> None:
    """Publish riko to PyPI."""
    cmd = ["publish", "--dry-run"] if dry_run else ["publish"]

    if _uv:
        check_call([_uv, *cmd])
    else:
        raise RuntimeError("uv not found")


def _twine_check() -> int:
    """Validate that built distributions render on PyPI."""
    dists = sorted(glob(str(ROOT_DIR / "dist" / "*")))
    inputs = [ROOT_DIR / "README.rst", ROOT_DIR / "pyproject.toml"]

    if not dists:
        raise RuntimeError("No distributions found in dist/; run `manage build` first")
    elif max(map(getmtime, inputs)) > min(map(getmtime, dists)):
        raise RuntimeError("dist/ is stale; run `manage build` first")
    elif _twine:
        cmd = [_twine, "check", *dists]
    elif _uv:
        cmd = [_uv, "run", "--active", "--with", "twine", "twine", "check", *dists]
    else:
        raise RuntimeError("twine not found")

    return call(cmd)


@click.command(name="clean")
def _clean_command() -> None:
    """Remove Python file and build artifacts."""
    _clean()


@click.command(name="build")
def _build_command() -> None:
    """Build the riko package."""
    try:
        _clean()
        _build()
    except CalledProcessError as e:
        exit(e.returncode)


@click.command(name="publish")
@click.option(
    "-d",
    "--dry-run",
    help="Rehearse the upload without publishing to PyPI",
    is_flag=True,
)
def _publish_command(dry_run: bool = False) -> None:
    """Publish riko to PyPI."""
    try:
        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


@click.command(name="release")
@click.option(
    "-d",
    "--dry-run",
    help="Build, check, and rehearse the upload without publishing",
    is_flag=True,
)
def _release_command(dry_run: bool = False) -> None:
    """Build and publish a new riko version."""
    try:
        _clean()
        _build()

        if return_code := _twine_check():
            exit(return_code)

        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


CLEAN_COMMAND = _clean_command
BUILD_COMMAND = _build_command
PUBLISH_COMMAND = _publish_command
RELEASE_COMMAND = _release_command
