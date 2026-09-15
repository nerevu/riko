# vim: sw=4:ts=4:expandtab

"""Test runner helpers for the manage CLI."""

import shutil
from subprocess import CalledProcessError, check_call
from sys import exit

import click

_tox: str | None = shutil.which("tox")
_pytest: str | None = shutil.which("pytest")


@click.command(name="test")
@click.argument("paths", nargs=-1)
@click.option("-w", "--where", help="test path (repeatable)", multiple=True)
@click.option("-x", "--stop", help="Stop after first error", is_flag=True)
@click.option(
    "-f", "--failed", help="Run failed tests (overrides --debug)", is_flag=True
)
@click.option(
    "-D",
    "--debug",
    help="Drop into pdb on failure (overridden by --failed)",
    is_flag=True,
)
@click.option("-W", "--watch", help="Rerun tests on file changes", is_flag=True)
@click.option("-c", "--cov/--no-cov", help="Add coverage report", default=True)
@click.option(
    "-C",
    "--capture/--no-capture",
    help="Capture stdout/sdterr (disables --watch)",
    default=True,
)
@click.option("-t", "--tox", help="Run tox tests", is_flag=True)
@click.option("-e", "--tox-env", help="Select tox test environment", default=None)
@click.option("-v", "--verbose", help="Use detailed errors", is_flag=True)
@click.option(
    "-q", "--quiet", help="Suppress per-test output (overridden by -v)", is_flag=True
)
@click.option(
    "-p", "--parallel", help="Run tests in parallel in multiple processes", is_flag=True
)
def _test_command(
    paths: tuple[str, ...] = (),  # noqa: PT028
    where: tuple[str, ...] = (),  # noqa: PT028
    stop: bool | None = None,  # noqa: PT028
    **kwargs: object,
) -> None:
    """Run pytest, tox, and script tests."""
    _where = [*where, *paths]

    if kwargs.get("quiet"):
        verbosity = "q"
    elif kwargs.get("verbose"):
        verbosity = "vv --tb=long -ra"
    else:
        verbosity = "v --tb=short -ra"

    opts = f"-x{verbosity}" if stop else f"-{verbosity}"
    opts += " --cov=riko" if kwargs.get("cov") else " --no-cov"
    opts += "" if kwargs.get("capture") else " -s"
    opts += " --last-failed" if kwargs.get("failed") else ""

    if kwargs.get("watch") and kwargs.get("capture"):
        opts += " --looponfail"

    if kwargs.get("debug"):
        opts += " --pdb -s"

    opts += f" {' '.join(_where)}" if _where else ""

    try:
        if _tox and kwargs.get("tox"):
            runner = ["p"] if kwargs.get("parallel") else ["r"]
            tox_env = kwargs.get("tox_env")
            topts = ["-e", str(tox_env)] if tox_env else []
            check_call([_tox] + topts + runner)
        elif kwargs.get("tox"):
            raise RuntimeError("tox not found")
        elif _pytest:
            cmd = opts

            if kwargs.get("parallel"):
                cmd += " -n auto"

            check_call([_pytest] + cmd.split(" "))
        else:
            raise RuntimeError("pytest not found")
    except CalledProcessError as e:
        exit(e.returncode)


TEST_COMMAND = _test_command
