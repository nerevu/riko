# vim: sw=4:ts=4:expandtab

"""Dependency upgrade helpers for the manage CLI."""

from __future__ import annotations

import shutil
from datetime import date
from subprocess import call
from sys import exit
from typing import TYPE_CHECKING

import click

from riko.base._paths import ROOT_DIR

from ._lint_deps import HOOK_PINNED, build_pinned_config, get_locked_version

if TYPE_CHECKING:
    from pathlib import Path

_uv: str | None = shutil.which("uv")
_UPGRADE_STAMP = ROOT_DIR / ".cache" / "last-upgrade"
_HOOK_CONFIG = ROOT_DIR / ".pre-commit-config.yaml"
_LOCKFILE = ROOT_DIR / "uv.lock"


def _upgrade_lock(uv: str, packages: tuple[str, ...] = ()) -> int:
    """Re-resolves ``uv.lock`` to the newest versions ``pyproject.toml`` allows."""
    upgrades = [f"--upgrade-package={name}" for name in packages] or ["--upgrade"]
    return call([uv, "lock", *upgrades])


def _pin_hooks(config: Path, lockfile: Path) -> None:
    """Rewrites the pre-commit tool pins to the versions ``uv.lock`` resolved."""
    text = config.read_text(encoding="utf-8")
    versions = {name: get_locked_version(lockfile, name) for name in HOOK_PINNED}
    pinned = build_pinned_config(text, versions)

    if pinned != text:
        config.write_text(pinned, encoding="utf-8")
        click.echo(f"Pinned {config.name} to the locked {', '.join(HOOK_PINNED)}.")


def _sync_environment(uv: str) -> int:
    """Syncs the active environment to the lock with every group and extra."""
    return call([uv, "sync", "--active", "--locked", "--group", "dev", "--all-extras"])


def _is_upgraded_today(stamp: Path) -> bool:
    """Checks whether a full upgrade and sync already succeeded today."""
    try:
        last = stamp.read_text().strip()
    except FileNotFoundError:
        last = ""

    return last == date.today().isoformat()


def _write_upgrade_stamp(stamp: Path) -> None:
    """Records today as the date of the last full upgrade and sync."""
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(date.today().isoformat())


@click.command(name="upgrade")
@click.option(
    "-p",
    "--package",
    help="Upgrade only this package instead of all (repeatable)",
    multiple=True,
)
@click.option(
    "--sync/--no-sync",
    help="Sync the active environment to the lock (default: sync)",
    default=True,
)
@click.option(
    "-d",
    "--daily",
    help="Skip if a full upgrade and sync already succeeded today",
    is_flag=True,
)
def _upgrade_command(
    package: tuple[str, ...] = (), sync: bool = True, daily: bool = False
) -> None:
    """
    Upgrade locked dependencies and sync the active environment.

    With no --package, every dependency moves to the newest version
    pyproject.toml allows. Only a full upgrade that also syncs counts
    toward --daily.
    """
    if not _uv:
        raise RuntimeError("uv not found")

    if daily and _is_upgraded_today(_UPGRADE_STAMP):
        click.echo("Dependencies were already upgraded today; skipping.")
        return_code = 0
    else:
        return_code = _upgrade_lock(_uv, package)

        if not return_code:
            _pin_hooks(_HOOK_CONFIG, _LOCKFILE)

        if sync and not return_code:
            return_code = _sync_environment(_uv)

        if sync and not (package or return_code):
            _write_upgrade_stamp(_UPGRADE_STAMP)

    exit(return_code)


UPGRADE_COMMAND = _upgrade_command
