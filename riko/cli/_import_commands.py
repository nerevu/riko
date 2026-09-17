"""Compose static import-contract checks for the manage CLI."""

from collections.abc import Callable
from pathlib import Path
from sys import exit

import click

from riko.base._paths import PACKAGE_DIR
from riko.base.exceptions import ImportLintError

from ._lint_canonical_imports import check_canonical_imports
from ._lint_import_architecture import (
    generate_report,
    render_architecture,
    validate_architecture,
)
from ._lint_relative_imports import check_relative_imports


def _check_architecture(root: Path) -> int:
    report = generate_report(root)
    print(render_architecture(report))
    return validate_architecture(report)


_IMPORT_CHECKS: dict[str, Callable[[Path], int]] = {
    "canonical": check_canonical_imports,
    "relative": check_relative_imports,
    "architecture": _check_architecture,
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
