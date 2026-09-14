"""Compose static import-contract checks for the manage CLI."""

from pathlib import Path
from sys import exit

import click

from riko.base._paths import PACKAGE_DIR

from ._lint_canonical_imports import _check_canonical_imports
from ._lint_import_architecture import check_import_architecture
from ._lint_relative_imports import _check_relative_imports


@click.group(name="imports")
def _imports_command() -> None:
    """Check Riko's internal import contracts."""


@_imports_command.command(name="canonical")
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=PACKAGE_DIR,
    show_default=True,
)
def _canonical_command(root: Path) -> None:
    """Reject imports through internal re-export facades."""
    exit(_check_canonical_imports(root))


@_imports_command.command(name="relative")
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=PACKAGE_DIR,
    show_default=True,
)
def _relative_command(root: Path) -> None:
    """Require relative imports between sibling modules."""
    exit(_check_relative_imports(root))


@_imports_command.command(name="architecture")
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=PACKAGE_DIR,
    show_default=True,
)
def _architecture_command(root: Path) -> None:
    """Render the observed layer graph and reject upward imports."""
    exit(check_import_architecture(root))


IMPORTS_COMMAND = _imports_command
