# vim: sw=4:ts=4:expandtab

"""Composes development commands under the ``manage`` CLI."""

import sys

import click

from riko.base._logging import set_log_level

from ._build import BUILD_COMMAND, CLEAN_COMMAND, PUBLISH_COMMAND, RELEASE_COMMAND
from ._codegen import CODEGEN_COMMAND
from ._lint import CHECK_COMMAND, LINT_COMMAND, PRETTIFY_COMMAND
from ._logging import exception_hook, resolve_log_level
from ._release import BACKFILL_COMMAND, MISSING_COMMAND, RELEASE_NOTES_COMMAND
from ._test import TEST_COMMAND
from ._upgrade import UPGRADE_COMMAND

sys.excepthook = exception_hook


@click.group()
@click.option(
    "-v",
    "--verbose",
    help="Specify multiple times to increase logging verbosity (overridden by -q)",
    count=True,
)
@click.option("-q", "--quiet", help="Only log errors (overrides -v)", is_flag=True)
def manager(verbose: int = 0, quiet: bool = False) -> None:
    """Run riko development tasks."""
    set_log_level(resolve_log_level(verbose, quiet))


@manager.command()
def hello() -> None:
    """Say hello."""
    print("Hello world")


@manager.command()
@click.pass_context
def help(ctx: click.Context) -> None:
    """Show available commands."""
    commands = "\n  ".join(manager.list_commands(ctx))
    print("Usage: manage <command> [OPTIONS]")
    print("commands:")
    print(f"  {commands}")


for _command in (
    BACKFILL_COMMAND,
    BUILD_COMMAND,
    CHECK_COMMAND,
    CLEAN_COMMAND,
    CODEGEN_COMMAND,
    LINT_COMMAND,
    MISSING_COMMAND,
    PRETTIFY_COMMAND,
    PUBLISH_COMMAND,
    RELEASE_COMMAND,
    RELEASE_NOTES_COMMAND,
    TEST_COMMAND,
    UPGRADE_COMMAND,
):
    manager.add_command(_command)


if __name__ == "__main__":
    manager()
