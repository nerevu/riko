# vim: sw=4:ts=4:expandtab

""" A script to manage development tasks """
import sys
from functools import partial
from os import environ
from os import path as p
from subprocess import CalledProcessError, call, check_call
from sys import exit

import click
from click import Choice

from riko.helpers import exception_hook

BASEDIR = p.dirname(__file__)
DEF_PY_WHERE = "riko examples bin helpers *.py"
CONFIG_MODES = ["Test", "Development", "Production"]
ARGS_KEY = f"{__name__}.args"

sys.excepthook = partial(exception_hook, debug=False)


def parse_verbosity(verbose=0, quiet=None):
    if quiet:
        verbosity = "0"
    elif verbose:
        verbosity = str(verbose)
    else:
        verbosity = ""

    return verbosity


@click.group()
@click.option(
    "-f",
    "--config-file",
    type=p.abspath,
    help="Loads a configuration from a file (overrides `config-envvar` and `config-mode`).",
)
@click.option(
    "-E",
    "--config-envvar",
    help="Loads a configuration from an environment variable pointing to a configuration file (overrides `config-mode`, overridden by `config-file`).",
)
@click.option(
    "-m",
    "--config-mode",
    type=Choice(CONFIG_MODES, case_sensitive=False),
    default="Development",
    help="Loads configuration from the preset mode (overridden by `config-file` and `config-envvar`).",
)
@click.option(
    "-v",
    "--verbose",
    help="Specify multiple times to increase logging verbosity (overridden by -q)",
    count=True,
)
@click.option("-q", "--quiet", help="Only log errors (overrides -v)", is_flag=True)
@click.pass_context
def manager(ctx, verbose=0, quiet=False, **kwargs):
    cmd = ctx.command.get_command(ctx, ctx.invoked_subcommand)
    args = ctx.meta.get(ARGS_KEY)
    cmd.parse_args(ctx, args)
    verbose = ctx.params["verbose"]
    environ["VERBOSITY"] = parse_verbosity(verbose, quiet)


@manager.command()
def hello():
    """Says hello"""
    print("Hello world")


@manager.command()
@click.pass_context
def help(ctx):
    """Show available commands"""
    commands = "\n  ".join(manager.list_commands(ctx))
    print("Usage: manage <command> [OPTIONS]")
    print("commands:")
    print(f"  {commands}")


def _clean():
    """Remove Python file and build artifacts"""
    check_call(p.join(BASEDIR, "helpers", "clean"))


@manager.command()
def check():
    """Check staged changes for lint errors"""
    exit(call(p.join(BASEDIR, "helpers", "check-stage")))


@manager.command()
@click.option("-w", "--where", help="Modules to check", default=DEF_PY_WHERE)
@click.option("-f", "--fix", help="Fix errors", is_flag=True)
@click.option("-s", "--strict", help="Check with pylint", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
def lint(where=DEF_PY_WHERE, fix=False, strict=False, parallel=False):
    """Check style with linters"""
    args = "pylint --rcfile=tests/standard.rc -rn -fparseable riko"
    args += " -j 0" if parallel else ""
    r_args = "ruff check --fix" if fix else "ruff check"
    r_args += f" {where}" if where else ""

    try:
        check_call(r_args.split(" "))
        check_call(args.split(" ")) if strict else None
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
@click.option("-w", "--where", help="Modules to check")
@click.option("-s", "--sort", help="Sort module imports", is_flag=True)
def prettify(where, sort=False):
    """Prettify code with ruff"""
    extra = where.split(" ") if where else []

    try:
        args = ["ruff", "check", "--select", "I", "--fix"]
        check_call(args + extra) if sort else None
        check_call(["ruff", "format"] + extra)
    except CalledProcessError as e:
        return_code = e.returncode
    else:
        return_code = 0

    exit(return_code)


@manager.command()
@click.option("-w", "--where", help="test path", default=None)
@click.option("-x", "--stop", help="Stop after first error", is_flag=True)
@click.option("-f", "--failed", help="Run failed tests", is_flag=True)
@click.option("-c", "--cover", help="Add coverage report", is_flag=True)
@click.option("-t", "--tox", help="Run tox tests", is_flag=True)
@click.option("-d", "--detox", help="Run detox tests", is_flag=True)
@click.option("-v", "--verbose", help="Use detailed errors", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run tests in parallel in multiple processes",
    is_flag=True,
)
def test(where=None, stop=None, **kwargs):
    """Run pytest, tox, and script tests"""
    opts = "-xv" if stop else "-v"
    opts += " --cov=riko" if kwargs.get("cover") else ""
    opts += " --last-failed" if kwargs.get("failed") else ""
    opts += " --numprocesses=auto" if kwargs.get("parallel") else ""
    opts += " --tb=long -ra" if kwargs.get("verbose") else ""
    opts += f" {where}" if where else ""

    try:
        if kwargs.get("tox") and kwargs.get("parallel"):
            check_call(["uv", "run", "tox", "-p"])
        elif kwargs.get("tox"):
            check_call("uv run tox", shell=True)
        else:
            check_call(("pytest %s" % opts).split(" "))
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
def build():
    """Build riko package"""
    try:
        _clean()
        check_call("uv build", shell=True)
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
@click.option("-d", "--dry-run", help="Test that the package can be installed and imported", is_flag=True)
def publish(dry_run=False):
    """Publish riko to PyPI"""
    if dry_run:
        cmd = 'uv run --with riko --no-project -- python -c "import riko"'
    else:
        cmd = "uv publish"

    check_call(cmd, shell=True)


@manager.command()
def clean():
    """Remove Python file and build artifacts"""
    try:
        _clean()
    except CalledProcessError as e:
        exit(e.returncode)


if __name__ == "__main__":
    manager()
