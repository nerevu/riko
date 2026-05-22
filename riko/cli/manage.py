# vim: sw=4:ts=4:expandtab

""" A script to manage development tasks """
import sys
from functools import partial
from os import environ
from os import path as p
from subprocess import CalledProcessError, call, check_call
from sys import exit

import click

from riko.helpers import exception_hook

BASEDIR = p.dirname(p.dirname(p.dirname(p.abspath(__file__))))

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
    "-v",
    "--verbose",
    help="Specify multiple times to increase logging verbosity (overridden by -q)",
    count=True,
)
@click.option("-q", "--quiet", help="Only log errors (overrides -v)", is_flag=True)
@click.pass_context
def manager(ctx, verbose=0, quiet=False, **kwargs):
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
    check_call(p.join(BASEDIR, "bin", "clean"))


def _build():
    """Build riko package"""
    check_call("uv build", shell=True)


def _publish(dry_run=False):
    """Publish riko to PyPI"""
    if dry_run:
        cmd = 'uv run --with riko --no-project -- python -c "import riko"'
    else:
        cmd = "uv publish"

    check_call(cmd, shell=True)


@manager.command()
def check():
    """Check staged changes for lint errors"""
    exit(call(p.join(BASEDIR, "bin", "check-stage")))


@manager.command()
@click.option("-w", "--where", help="Modules to check")
@click.option("-f", "--fix", help="Fix errors", is_flag=True)
@click.option("-s", "--strict", help="Check with pylint", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
def lint(where=None, fix=False, strict=False, parallel=False):
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
@click.option("-c", "--cover/--no-cover", help="Add coverage report")
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
    opts += " --cov=riko" if kwargs.get("cover") else " --no-cov"
    opts += " --last-failed" if kwargs.get("failed") else ""
    opts += " --tb=long -ra" if kwargs.get("verbose") else ""
    opts += f" {where}" if where else ""

    try:
        if kwargs.get("tox") and kwargs.get("parallel"):
            check_call(["uv", "run", "tox", "-p", "auto"])
        elif kwargs.get("tox"):
            check_call("uv run tox", shell=True)
        else:
            params = ("pytest %s" % opts).split(" ")

            if kwargs.get("parallel"):
                params += ["-n", "auto"]

            check_call(params)
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
def clean():
    """Remove Python file and build artifacts"""
    try:
        _clean()
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
def build():
    """Build riko package"""
    try:
        _clean()
        _build()
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
@click.option("-d", "--dry-run", help="Test that the package can be installed and imported", is_flag=True)
def publish(dry_run=False):
    """Publish riko to PyPI"""
    try:
        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)



@manager.command()
@click.option("-d", "--dry-run", help="Test that the package can be installed and imported", is_flag=True)
def release(dry_run=False):
    """Build and publish new riko version"""
    try:
        _build()
        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


if __name__ == "__main__":
    manager()
