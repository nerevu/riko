"""Compose static import-contract checks for the manage CLI."""

from __future__ import annotations

from pathlib import Path
from sys import exit
from typing import TYPE_CHECKING

import click

from riko.base._paths import PACKAGE_DIR
from riko.base.exceptions import ImportLintError

from ._lint_canonical_imports import lint_canonical_imports
from ._lint_import_architecture import (
    lint_architecture,
    load_architecture_report,
    render_architecture,
)
from ._lint_relative_imports import lint_relative_imports

if TYPE_CHECKING:
    from collections.abc import Callable


def _lint_architecture_imports(root: Path) -> int:
    report = load_architecture_report(root)
    print(render_architecture(report))
    return lint_architecture(report)


_IMPORT_CHECKS: dict[str, Callable[[Path], int]] = {
    "canonical": lint_canonical_imports,
    "relative": lint_relative_imports,
    "architecture": _lint_architecture_imports,
}


def run_import_checks(root: Path, *checks: str) -> int:
    return_code = 0

    for name in checks:
        try:
            check_code = _IMPORT_CHECKS[name](root)
        except ImportLintError as e:
            click.echo(f"error: {e}", err=True)
            check_code = 2

        return_code = max(return_code, check_code)

    return return_code


@click.command(name="imports")
@click.option(
    "--root",
    type=click.Path(path_type=Path, file_okay=False),
    default=PACKAGE_DIR,
    show_default=True,
)
@click.option(
    "--canonical",
    help="Reject imports through internal re-export facades",
    is_flag=True,
)
@click.option(
    "--relative", help="Require relative imports between sibling modules", is_flag=True
)
@click.option(
    "--architecture", help="Reject forbidden package-layer imports", is_flag=True
)
@click.option("--all", "all_", help="Run every import-contract check", is_flag=True)
def _imports_command(
    root: Path,
    canonical: bool = False,
    relative: bool = False,
    architecture: bool = False,
    all_: bool = False,
) -> None:
    """Check Riko's internal import contracts."""
    if all_:
        selected = _IMPORT_CHECKS
    else:
        selections = (
            ("canonical", canonical),
            ("relative", relative),
            ("architecture", architecture),
        )
        selected = tuple(name for name, enabled in selections if enabled)
    selected = selected or ("canonical",)
    exit(run_import_checks(root, *selected))


IMPORTS_COMMAND = _imports_command
