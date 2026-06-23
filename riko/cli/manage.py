# vim: sw=4:ts=4:expandtab

"""A script to manage development tasks"""

import shutil
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

uv = shutil.which("uv")
tox = shutil.which("tox")
detox = shutil.which("detox")
pytest = shutil.which("pytest")
ruff = shutil.which("ruff")
pylint = shutil.which("pylint")


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
def manager(verbose=0, quiet=False):
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
    if uv:
        check_call([uv, "build"])
    else:
        raise RuntimeError("uv not found")


def _publish(dry_run=False):
    """Publish riko to PyPI"""
    if dry_run:
        cmd = 'run --with riko --no-project -- python -c "import riko"'
    else:
        cmd = "publish"

    if uv:
        check_call([uv] + cmd.split(" "))
    else:
        raise RuntimeError("uv not found")


@manager.command()
def check():
    """Check staged changes for lint errors"""
    exit(call(p.join(BASEDIR, "bin", "check-stage")))


@manager.command()
@click.option("-w", "--where", help="Modules to check")
@click.option("-f", "--fix", help="Fix errors", is_flag=True)
@click.option(
    "-F",
    "--unsafe-fixes",
    help="View unsafe fixes (Applies unsafe fixes if --fix is also specified)",
    is_flag=True,
)
@click.option("-s", "--strict", help="Check with pylint", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
def lint(where=None, fix=False, unsafe_fixes=False, strict=False, parallel=False):
    """Check style with linters"""
    where = where or ""
    r_args = ["check"]

    if fix:
        r_args.append("--fix")

    if unsafe_fixes:
        r_args.append("--unsafe-fixes")

    if where:
        r_args.extend(where.split(" "))

    if ruff:
        try:
            check_call([ruff] + r_args)
        except CalledProcessError as e:
            exit(e.returncode)
    else:
        raise RuntimeError("ruff not found")

    if strict and pylint:
        args = [pylint, "--rcfile=tests/standard.rc", "-rn", "-fparseable", "riko"]

        if parallel:
            args.extend(["-j", "0"])

        try:
            check_call(args)
        except CalledProcessError as e:
            exit(e.returncode)
    elif strict:
        raise RuntimeError("pylint not found")


@manager.command()
@click.option("-w", "--where", help="Modules to check", default=None)
@click.option("-s", "--sort", help="Sort module imports", is_flag=True)
def prettify(where=None, sort=False):
    """Prettify code with ruff"""
    where = where or ""
    return_code = 0

    if sort and ruff:
        cmd = [ruff, "check", "--select", "I", "--fix"]

        if where:
            cmd.extend(where.split(" "))

        try:
            check_call(cmd)
        except CalledProcessError as e:
            return_code = e.returncode
        else:
            return_code = 0
    elif sort:
        raise RuntimeError("ruff not found")

    if ruff and not return_code:
        cmd = [ruff, "format"]

        if where:
            cmd.extend(where.split(" "))

        try:
            check_call(cmd)
        except CalledProcessError as e:
            return_code = e.returncode
        else:
            return_code = 0
    elif not return_code:
        raise RuntimeError("ruff not found")

    exit(return_code)


@manager.command()
@click.option("-w", "--where", help="test path", default=None)
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
@click.option("-d", "--detox", help="Run detox tests", is_flag=True)
@click.option("-v", "--verbose", help="Use detailed errors", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run tests in parallel in multiple processes",
    is_flag=True,
)
def test(where=None, stop=None, **kwargs):  # noqa: PT028
    """Run pytest, tox, and script tests"""
    opts = "-xv" if stop else "-v"
    opts += " --cov=riko" if kwargs.get("cover") else " --no-cov"
    opts += "" if kwargs.get("capture") else " -s"
    opts += " --last-failed" if kwargs.get("failed") else ""
    opts += " -vv --tb=long -ra" if kwargs.get("verbose") else " --tb=short -ra"

    if kwargs.get("watch") and kwargs.get("capture"):
        opts += " --looponfail"
    elif kwargs.get("debug"):
        opts += " --pdb"

    opts += f" {where}" if where else ""

    try:
        if tox and kwargs.get("tox") and kwargs.get("parallel"):
            check_call([tox, "-p", "auto"])
        elif tox and kwargs.get("tox"):
            check_call([tox])
        elif kwargs.get("tox"):
            raise RuntimeError("tox not found")
        elif detox and kwargs.get("detox"):
            pass
        elif kwargs.get("detox"):
            raise RuntimeError("detox not found")
        elif pytest:
            cmd = opts

            if kwargs.get("parallel"):
                cmd += " -n auto"

            check_call([pytest] + cmd.split(" "))
        else:
            raise RuntimeError("pytest not found")

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
@click.option(
    "-d",
    "--dry-run",
    help="Test that the package can be installed and imported",
    is_flag=True,
)
def publish(dry_run=False):
    """Publish riko to PyPI"""
    try:
        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
@click.option(
    "-d",
    "--dry-run",
    help="Test that the package can be installed and imported",
    is_flag=True,
)
def release(dry_run=False):
    """Build and publish new riko version"""
    try:
        _build()
        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


if __name__ == "__main__":
    manager()
