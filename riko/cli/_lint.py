# vim: sw=4:ts=4:expandtab

"""Lint and formatting helpers for the manage CLI."""

import shutil
from collections.abc import Iterable
from glob import glob
from itertools import chain
from pathlib import Path
from subprocess import CalledProcessError, call, check_call, check_output
from sys import exit

import click

from riko.base._paths import ROOT_DIR

from ._build import _twine_check
from ._docs import _check_docs, _check_rst
from ._docstyle import format_issue, iter_summary_issues

_WORKFLOW_DIR = ROOT_DIR / ".github" / "workflows"

_ruff: str | None = shutil.which("ruff")
_pylint: str | None = shutil.which("pylint")
_pyright: str | None = shutil.which("pyright")
_actionlint: str | None = shutil.which("actionlint")
_shellcheck: str | None = shutil.which("shellcheck")
_yamlfmt: str | None = shutil.which("yamlfmt")


def _check_types(where: str | None = None) -> int:
    """Check type annotations with pyright."""
    if not _pyright:
        raise RuntimeError("pyright not found")

    paths = where.split(" ") if where else []
    return call([_pyright, "-p", "pyproject.toml", *paths])


def _verify_types(where: str | None = None) -> int:
    """Verify type completeness with pyright."""
    if not _pyright:
        raise RuntimeError("pyright not found")

    paths = where.split(" ") if where else []
    return call(
        [
            _pyright,
            "-p",
            "pyproject.toml",
            "--verifytypes",
            "riko",
            "--ignoreexternal",
            *paths,
        ]
    )


def _pylint_check(parallel: bool = False) -> int:
    """Check style with pylint."""
    if not _pylint:
        raise RuntimeError("pylint not found")

    args = [_pylint, "--rcfile=tests/standard.rc", "-rn", "-fparseable", "riko"]

    if parallel:
        args.extend(["-j", "0"])

    return call(args)


def _docstring_check(where: str | None = "") -> int:
    """Check that no docstring summary leads with Returns or Yields."""
    roots = [Path(p) for p in where.split(" ")] if where else [Path("riko")]
    issues = list(iter_summary_issues(*roots))

    for issue in issues:
        print(format_issue(issue))

    return 1 if issues else 0


def _ruff_check(where: str | None = "", unsafe_fixes: bool = False) -> int:
    """Check style and formatting with ruff."""
    if not _ruff:
        raise RuntimeError("ruff not found")

    paths = where.split(" ") if where else []
    args = [_ruff, "check"]

    if unsafe_fixes:
        args.append("--unsafe-fixes")

    return call([*args, *paths]) or call([_ruff, "format", "--check", *paths])


def _gen_yaml_files() -> Iterable[str]:
    """Collect tracked YAML files."""
    args = ["git", "ls-files", "*.yml", "*.yaml"]
    yield from check_output(args, text=True).splitlines()


def _check_actions(where: Iterable[str]) -> int:
    """Validate GitHub Actions workflows with actionlint and shellcheck."""
    if not _actionlint:
        raise RuntimeError("actionlint not found")
    elif not _shellcheck:
        raise RuntimeError("shellcheck not found")

    return call([_actionlint, *where])


def _check_yaml(where: Iterable[str] = ()) -> int:
    """Lint YAML files with yamlfmt."""
    if not _yamlfmt:
        raise RuntimeError("yamlfmt not found")

    paths = where or _gen_yaml_files()
    return call([_yamlfmt, "-lint", *paths])


def _get_staged() -> list[str]:
    """List staged Python files that were added, copied, or modified."""
    args = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    staged = check_output(args, text=True).splitlines()
    return [name for name in staged if name.endswith(".py")]


def _check_staged() -> int:
    """Lint staged Python files with ruff."""
    if not _ruff:
        raise RuntimeError("ruff not found")

    files = _get_staged()

    if not files:
        return_code = 0
    else:
        return_code = call([_ruff, "check", *files]) or call(
            [_ruff, "format", "--check", *files]
        )

    return return_code


def _format_yaml(where: Iterable[str] = ()) -> int:
    """Format YAML files with yamlfmt."""
    if not _yamlfmt:
        raise RuntimeError("yamlfmt not found")

    paths = where or _gen_yaml_files()
    return call([_yamlfmt, *paths])


@click.command(name="check")
def _check_command() -> None:
    """Lint staged Python changes with ruff."""
    exit(_check_staged())


@click.command(name="lint")
@click.argument("paths", nargs=-1)
@click.option("-w", "--where", help="Modules to check (repeatable)", multiple=True)
@click.option("-F", "--unsafe-fixes", help="View unsafe fixes", is_flag=True)
@click.option("-t", "--check-types", help="Check with pyright", is_flag=True)
@click.option("-T", "--verify-types", help="Verify with pyright", is_flag=True)
@click.option("-s", "--strict", help="Check with pylint", is_flag=True)
@click.option("-d", "--dist", help="Check built distributions with twine", is_flag=True)
@click.option(
    "-r", "--rst", help="Validate RST rendering and internal links", is_flag=True
)
@click.option("--docs", help="Validate internal documentation policy", is_flag=True)
@click.option("-a", "--actions", help="Validate GitHub Actions workflows", is_flag=True)
@click.option("-y", "--yaml", help="Validate YAML files", is_flag=True)
@click.option("-D", "--docstrings", help="Check docstring summary style", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
def _lint_command(
    paths: tuple[str, ...] = (),
    where: tuple[str, ...] = (),
    unsafe_fixes: bool = False,
    strict: bool = False,
    check_types: bool = False,
    verify_types: bool = False,
    dist: bool = False,
    rst: bool = False,
    docs: bool = False,
    actions: bool = False,
    yaml: bool = False,
    docstrings: bool = False,
    parallel: bool = False,
) -> None:
    """Check style with linters."""
    _where = " ".join([*where, *paths])

    if dist:
        return_code = _twine_check()
    elif check_types:
        return_code = _check_types(_where)
    elif verify_types:
        return_code = _verify_types(_where)
    elif strict:
        return_code = _pylint_check(parallel)
    elif rst:
        return_code = _check_rst(_where)
    elif docs:
        return_code = _check_docs()
    elif docstrings:
        return_code = _docstring_check(_where)
    elif actions:
        exts = [".yml", ".yaml"]
        _paths = (glob(str(_WORKFLOW_DIR / f"*.{ext}")) for ext in exts)
        return_code = _check_actions(chain.from_iterable(_paths))
    elif yaml:
        return_code = _check_yaml(_where)
    else:
        return_code = _ruff_check(_where, unsafe_fixes)

    exit(return_code)


@click.command(name="prettify")
@click.option("-w", "--where", help="Modules to check", multiple=True)
@click.option("-s", "--sort/--no-sort", help="Sort module imports", default=True)
@click.option("-y", "--yaml", help="Format YAML files", is_flag=True)
@click.option("-F", "--unsafe-fixes", help="Applies unsafe fixes", is_flag=True)
def _prettify_command(
    where: tuple[str, ...] = (),
    sort: bool = True,
    yaml: bool = False,
    gen_config: bool = False,
    unsafe_fixes: bool = False,
) -> None:
    """Prettify code with ruff."""
    return_code = 0

    if yaml:
        return_code = _format_yaml(where)
    elif sort and _ruff:
        sort_cmd = [_ruff, "check", "--select", "I", "--fix"]
        style_cmd = [_ruff, "check", "--fix"]

        if unsafe_fixes:
            style_cmd.append("--unsafe-fixes")

        if where:
            sort_cmd.extend(where)
            style_cmd.extend(where)

        try:
            check_call(sort_cmd)
            check_call(style_cmd)
        except CalledProcessError as e:
            return_code = e.returncode
        else:
            return_code = 0
    elif sort:
        raise RuntimeError("ruff not found")

    if _ruff and not return_code:
        cmd = [_ruff, "format"]

        if where:
            cmd.extend(where)

        try:
            check_call(cmd)
        except CalledProcessError as e:
            return_code = e.returncode
        else:
            return_code = 0
    elif not return_code:
        raise RuntimeError("ruff not found")

    exit(return_code)


CHECK_COMMAND = _check_command
LINT_COMMAND = _lint_command
PRETTIFY_COMMAND = _prettify_command
