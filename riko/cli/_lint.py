# vim: sw=4:ts=4:expandtab

"""Lint and formatting helpers for the manage CLI."""

from __future__ import annotations

import shutil
from glob import glob
from itertools import chain
from pathlib import Path
from subprocess import CalledProcessError, call, check_call, check_output
from sys import exit
from typing import TYPE_CHECKING

import click

from riko.base._paths import PACKAGE_DIR, ROOT_DIR

from ._build import _twine_check
from ._docs import _lint_docs, _lint_rst
from ._docstyle import format_issue, gen_docstring_issues
from ._import_commands import _IMPORT_CHECKS, IMPORTS_COMMAND, run_import_checks
from ._lint_deps import (
    format_dependency_issue,
    gen_dependency_issues,
    gen_hook_pin_issues,
)
from ._lint_literals import format_literal_issue, gen_literal_issues
from ._lint_terms import format_term_issue, gen_term_issues
from ._lint_tests import format_layout_issue, gen_layout_issues

if TYPE_CHECKING:
    from collections.abc import Iterable

_WORKFLOW_DIR = ROOT_DIR / ".github" / "workflows"
_TEXT_ROOTS: tuple[str, ...] = (
    "riko",
    "tests",
    "examples",
    "docs",
    "README.rst",
    "CONTRIBUTING.rst",
)

_ruff: str | None = shutil.which("ruff")
_pylint: str | None = shutil.which("pylint")
_pyright: str | None = shutil.which("pyright")
_actionlint: str | None = shutil.which("actionlint")
_shellcheck: str | None = shutil.which("shellcheck")
_yamlfmt: str | None = shutil.which("yamlfmt")


def _lint_types(where: str | None = None) -> int:
    """Checks type annotations with pyright."""
    if not _pyright:
        raise RuntimeError("pyright not found")

    paths = where.split(" ") if where else []
    return call([_pyright, "-p", "pyproject.toml", *paths])


def _verify_types(where: str | None = None) -> int:
    """Verifies type completeness with pyright."""
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


def _lint_python_strict(parallel: bool = False) -> int:
    """Checks style with pylint."""
    if not _pylint:
        raise RuntimeError("pylint not found")

    args = [_pylint, "-rn", "-fparseable", "riko"]

    if parallel:
        args.extend(["-j", "0"])

    return call(args)


def _lint_docstrings(where: str | None = "") -> int:
    """Checks docstring summaries and the prose between doctest examples."""
    roots = [Path(p) for p in where.split(" ")] if where else [Path("riko")]
    issues = list(gen_docstring_issues(*roots))

    for issue in issues:
        print(format_issue(issue))

    return 1 if issues else 0


def _lint_terms(where: str | None = "") -> int:
    """Checks shipped text for phrases the reserved-terms rules replace."""
    names = where.split(" ") if where else _TEXT_ROOTS
    issues = list(gen_term_issues(*(ROOT_DIR / name for name in names)))

    for issue in issues:
        print(format_term_issue(issue))

    return 1 if issues else 0


def _lint_literals(where: str | None = "") -> int:
    """Checks shipped text for inline literals that break the quoting rules."""
    names = where.split(" ") if where else _TEXT_ROOTS
    issues = list(gen_literal_issues(*(ROOT_DIR / name for name in names)))

    for issue in issues:
        print(format_literal_issue(issue))

    return 1 if issues else 0


def _lint_tests() -> int:
    """Checks the test suite against its indexed layout."""
    issues = list(gen_layout_issues(ROOT_DIR / "tests"))

    for issue in issues:
        print(format_layout_issue(issue))

    return 1 if any(issue.fatal for issue in issues) else 0


def _lint_deps() -> int:
    """Checks riko's imports and hook pins against its declared and locked deps."""
    pyproject = ROOT_DIR / "pyproject.toml"
    hooks = ROOT_DIR / ".pre-commit-config.yaml"
    issues = [
        *gen_dependency_issues(PACKAGE_DIR, pyproject),
        *gen_hook_pin_issues(hooks, ROOT_DIR / "uv.lock"),
    ]

    for issue in issues:
        print(format_dependency_issue(issue))

    return 1 if issues else 0


def _lint_python(where: str | None = "", unsafe_fixes: bool = False) -> int:
    """Checks style and formatting with ruff."""
    if not _ruff:
        raise RuntimeError("ruff not found")

    paths = where.split(" ") if where else []
    args = [_ruff, "check"]

    if unsafe_fixes:
        args.append("--unsafe-fixes")

    return call([*args, *paths]) or call([_ruff, "format", "--check", *paths])


def _gen_yaml_files() -> Iterable[str]:
    """Collects tracked YAML files."""
    args = ["git", "ls-files", "*.yml", "*.yaml"]
    yield from check_output(args, text=True).splitlines()


def _lint_actions(*where: str) -> int:
    """Validates GitHub Actions workflows with actionlint and shellcheck."""
    if not _actionlint:
        raise RuntimeError("actionlint not found")
    elif not _shellcheck:
        raise RuntimeError("shellcheck not found")

    return call([_actionlint, *where])


def _lint_yaml(*where: str) -> int:
    """Lints YAML files with yamlfmt."""
    if not _yamlfmt:
        raise RuntimeError("yamlfmt not found")

    paths = where or _gen_yaml_files()
    return call([_yamlfmt, "-lint", *paths])


def _load_staged() -> list[str]:
    """Lists staged Python files that were added, copied, or modified."""
    args = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    staged = check_output(args, text=True).splitlines()
    return [name for name in staged if name.endswith(".py")]


def _lint_staged() -> int:
    """Lints staged Python files with ruff."""
    if not _ruff:
        raise RuntimeError("ruff not found")

    files = _load_staged()

    if not files:
        return_code = 0
    else:
        return_code = call([_ruff, "check", *files]) or call(
            [_ruff, "format", "--check", *files]
        )

    return return_code


def _format_yaml(*where: str) -> int:
    """Formats YAML files with yamlfmt."""
    if not _yamlfmt:
        raise RuntimeError("yamlfmt not found")

    paths = where or _gen_yaml_files()
    return call([_yamlfmt, *paths])


@click.command(name="check")
def _check_command() -> None:
    """Lint staged Python changes with ruff."""
    exit(_lint_staged())


@click.group(name="lint", invoke_without_command=True)
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
@click.option(
    "-D",
    "--docstrings",
    help="Check docstring summaries and example prose",
    is_flag=True,
)
@click.option("--terms", help="Check shipped text for replaced terms", is_flag=True)
@click.option(
    "--literals", help="Check shipped text for misquoted literals", is_flag=True
)
@click.option(
    "--deps", help="Check imports against declared dependencies", is_flag=True
)
@click.option("--tests", help="Check the test suite's indexed layout", is_flag=True)
@click.option("--all", "all_", help="Run every standard lint check", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
@click.pass_context
def _lint_command(
    ctx: click.Context,
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
    terms: bool = False,
    literals: bool = False,
    deps: bool = False,
    tests: bool = False,
    all_: bool = False,
    parallel: bool = False,
) -> None:
    """Check style, documentation, and internal contracts."""
    if ctx.invoked_subcommand is None:
        _where = " ".join(where)
        has_selector = any(
            (
                strict,
                check_types,
                verify_types,
                dist,
                rst,
                docs,
                actions,
                yaml,
                docstrings,
                terms,
                literals,
                deps,
                tests,
                all_,
            )
        )
        return_codes: list[int] = []

        if all_ or not has_selector:
            return_codes.append(_lint_python(_where, unsafe_fixes))

        if rst or all_:
            return_codes.append(_lint_rst(_where))

        if docs or all_:
            return_codes.append(_lint_docs())

        if docstrings or all_:
            return_codes.append(_lint_docstrings(_where))

        if terms or all_:
            return_codes.append(_lint_terms(_where))

        if literals or all_:
            return_codes.append(_lint_literals(_where))

        if deps or all_:
            return_codes.append(_lint_deps())

        if tests or all_:
            return_codes.append(_lint_tests())

        if actions or all_:
            exts = ["yml", "yaml"]
            paths = (glob(str(_WORKFLOW_DIR / f"*.{ext}")) for ext in exts)
            return_codes.append(_lint_actions(*chain.from_iterable(paths)))

        if yaml or all_:
            return_codes.append(_lint_yaml(*where))

        if all_:
            return_codes.append(run_import_checks(PACKAGE_DIR, *_IMPORT_CHECKS))

        if dist:
            return_codes.append(_twine_check())

        if check_types:
            return_codes.append(_lint_types(_where))

        if verify_types:
            return_codes.append(_verify_types(_where))

        if strict:
            return_codes.append(_lint_python_strict(parallel))

        exit(max(return_codes, default=0))


_lint_command.add_command(IMPORTS_COMMAND)


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
        return_code = _format_yaml(*where)
    elif _ruff:
        cmd = [_ruff, "format"]

        if where:
            cmd.extend(where)

        try:
            check_call(cmd)
        except CalledProcessError as e:
            return_code = e.returncode
        else:
            return_code = 0

        if sort and not return_code:
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
    else:
        raise RuntimeError("ruff not found")

    exit(return_code)


CHECK_COMMAND = _check_command
LINT_COMMAND = _lint_command
PRETTIFY_COMMAND = _prettify_command
