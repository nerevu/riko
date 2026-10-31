# vim: sw=4:ts=4:expandtab

"""Lint and formatting helpers for the manage CLI."""

from __future__ import annotations

import shutil
from collections import Counter
from functools import partial
from glob import glob
from itertools import chain
from pathlib import Path
from subprocess import CalledProcessError, call, check_call, check_output
from sys import exit
from typing import TYPE_CHECKING, Protocol

import click

from riko.base._paths import PACKAGE_DIR, PYPROJECT, ROOT_DIR, TESTS_DIR

from ._build import twine_check
from ._docs import AS_BUILT_DOCS, lint_docs
from ._docstyle import gen_docstring_issues
from ._import_commands import IMPORT_CHECKS, IMPORTS_COMMAND, run_import_checks
from ._lint_basenames import gen_basename_issues
from ._lint_bindings import gen_binding_issues
from ._lint_deps import gen_hook_pin_issues, gen_import_issues
from ._lint_escapes import ESCAPES, gen_escape_counts
from ._lint_literals import gen_literal_issues
from ._lint_rst import lint_rst
from ._lint_terms import gen_phrase_issues, gen_term_issues
from ._lint_tests import (
    LayoutIssue,
    gen_global_bound_issues,
    gen_inline_tables,
    gen_layout_issues,
    gen_rows_without_id,
    get_backstop,
)
from ._ratchet import ratchet_ceiling

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
_deptry: str | None = shutil.which("deptry")
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


class _IssueWalker[I](Protocol):
    """Walks shipped-text roots for one lint's issues."""

    def __call__(self, *roots: Path) -> Iterable[I]: ...


def _report_text_lint[I](gen: _IssueWalker[I], *roots: Path) -> int:
    """Runs one text lint over ``roots`` and prints each issue it finds."""
    issues = list(gen(*roots))

    for issue in issues:
        print(issue)

    return 1 if issues else 0


def _run_text_lint[I](gen: _IssueWalker[I], where: str | None = "") -> int:
    """Runs one shipped-text lint over ``where`` (or the text roots) and reports it."""
    names = where.split(" ") if where else _TEXT_ROOTS
    return _report_text_lint(gen, *(ROOT_DIR / name for name in names))


def _lint_docstrings(where: str | None = "") -> int:
    """Checks docstring summaries and doctest examples against the docs standard."""
    roots = [Path(p) for p in where.split(" ")] if where else [Path("riko")]
    return _report_text_lint(gen_docstring_issues, *roots)


def _lint_terms(where: str | None = "") -> int:
    """
    Checks shipped text and the as-built docs for banned wording.

    Shipped text is held to the banned phrases, phase codes, and removed paths; the
    as-built docs only to the banned phrases, since they cite phases by design.

    Args:

        where: Space-separated files or directories to check instead of the
            shipped-text roots; the as-built docs are then left out.

    Returns:

        ``1`` when any issue was found, else ``0``.

    """
    shipped = _run_text_lint(gen_term_issues, where)
    internal = 0 if where else _report_text_lint(gen_phrase_issues, *AS_BUILT_DOCS)
    return max(shipped, internal)


_lint_literals = partial(_run_text_lint, gen_literal_issues)
_lint_bindings = partial(_run_text_lint, gen_binding_issues)


def _ratchet_sites(key: str, noun: str, *sites: LayoutIssue) -> int:
    """Checks a count of test sites against its ceiling and prints them when over it."""
    if code := ratchet_ceiling(PYPROJECT, "tests", key, len(sites), noun):
        for site in sites:
            print(site)

    return code


def _lint_tests() -> int:
    """Checks the test suite against its tier layout, generated indexes, and bounds."""
    text = PYPROJECT.read_text(encoding="utf-8")

    if (backstop := get_backstop(text)) is None:
        raise RuntimeError("pyproject.toml sets no [tool.pytest.ini_options] timeout")

    issues = [
        *gen_global_bound_issues(text, PYPROJECT),
        *gen_layout_issues(TESTS_DIR, backstop),
    ]

    for issue in issues:
        print(issue)

    tables = gen_inline_tables(TESTS_DIR)
    rows = gen_rows_without_id(TESTS_DIR)
    noun = "inline multi-line parametrize tables"
    codes = [
        1 if any(issue.fatal for issue in issues) else 0,
        _ratchet_sites("inline-tables", noun, *tables),
        _ratchet_sites("rows-without-id", "`pytest.param` rows without `id=`", *rows),
    ]
    return max(codes)


def _lint_basenames() -> int:
    """Checks that no two package modules share a file name."""
    return _report_text_lint(gen_basename_issues, PACKAGE_DIR)


def _lint_escapes() -> int:
    """Checks the package's ``Any`` and ``cast`` uses against their ceilings."""
    totals = sum((counts for _, counts in gen_escape_counts(PACKAGE_DIR)), Counter())
    ratchet = partial(ratchet_ceiling, PYPROJECT, "typing")
    codes = [
        ratchet(escape.lower(), totals[escape], f"`{escape}` uses")
        for escape in ESCAPES
    ]
    return max(codes)


def _lint_deps() -> int:
    """Checks imports with deptry, then the run-time, guard, and pin rules it leaves."""
    if not _deptry:
        raise RuntimeError("deptry not found")

    hooks = ROOT_DIR / ".pre-commit-config.yaml"
    deptry_code = call([_deptry, "."], cwd=ROOT_DIR)
    issues = [
        *gen_import_issues(PACKAGE_DIR, PYPROJECT),
        *gen_hook_pin_issues(hooks, ROOT_DIR / "uv.lock"),
    ]

    for issue in issues:
        print(issue)

    return max(deptry_code, 1 if issues else 0)


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
    "-D", "--docstrings", help="Check docstring summaries and examples", is_flag=True
)
@click.option("--terms", help="Check shipped text for replaced terms", is_flag=True)
@click.option(
    "--literals", help="Check shipped text for misquoted literals", is_flag=True
)
@click.option(
    "--deps",
    help="Check imports and hook pins against package dependencies",
    is_flag=True,
)
@click.option(
    "--bindings", help="Check Workflow values are bound as flow", is_flag=True
)
@click.option("--tests", help="Check the test suite's tier layout", is_flag=True)
@click.option(
    "--basenames", help="Check package modules for shared file names", is_flag=True
)
@click.option(
    "--escapes",
    help="Check Any and cast uses against their recorded ceilings",
    is_flag=True,
)
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
    bindings: bool = False,
    tests: bool = False,
    basenames: bool = False,
    escapes: bool = False,
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
                bindings,
                tests,
                basenames,
                escapes,
                all_,
            )
        )
        return_codes: list[int] = []

        if all_ or not has_selector:
            return_codes.append(_lint_python(_where, unsafe_fixes))

        if rst or all_:
            return_codes.append(lint_rst(_where))

        if docs or all_:
            return_codes.append(lint_docs())

        if docstrings or all_:
            return_codes.append(_lint_docstrings(_where))

        if terms or all_:
            return_codes.append(_lint_terms(_where))

        if literals or all_:
            return_codes.append(_lint_literals(_where))

        if deps or all_:
            return_codes.append(_lint_deps())

        if bindings or all_:
            return_codes.append(_lint_bindings(_where))

        if tests or all_:
            return_codes.append(_lint_tests())

        if basenames or all_:
            return_codes.append(_lint_basenames())

        if escapes or all_:
            return_codes.append(_lint_escapes())

        if actions or all_:
            exts = ["yml", "yaml"]
            paths = (glob(str(_WORKFLOW_DIR / f"*.{ext}")) for ext in exts)
            return_codes.append(_lint_actions(*chain.from_iterable(paths)))

        if yaml or all_:
            return_codes.append(_lint_yaml(*where))

        if all_:
            return_codes.append(run_import_checks(PACKAGE_DIR, *IMPORT_CHECKS))

        if dist:
            return_codes.append(twine_check())

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
