# vim: sw=4:ts=4:expandtab

"""A script to manage development tasks"""

import re
import shutil
import sys
from functools import partial
from glob import glob
from io import StringIO
from os import environ
from os.path import basename, dirname, exists, getmtime, join
from subprocess import CalledProcessError, call, check_call
from sys import exit
from typing import Any

import click
from click import Choice

from riko._logging import exception_hook
from riko.cli.gen_config import main as gen_config_main
from riko.cli.gen_names import main as gen_names_main
from riko.paths import ROOT_DIR

try:
    from docutils import nodes
    from docutils.core import publish_doctree
except ImportError:
    publish_doctree = None
    nodes = None

sys.excepthook = partial(exception_hook, debug=False)

uv: str | None = shutil.which("uv")
tox: str | None = shutil.which("tox")
pytest: str | None = shutil.which("pytest")
ruff: str | None = shutil.which("ruff")
pylint: str | None = shutil.which("pylint")
pyright: str | None = shutil.which("pyright")
twine: str | None = shutil.which("twine")


def parse_verbosity(verbose: int = 0, quiet: bool | None = None) -> str:
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
def manager(verbose: int = 0, quiet: bool = False) -> None:
    environ["VERBOSITY"] = parse_verbosity(verbose, quiet)


@manager.command()
def hello():
    """Says hello"""
    print("Hello world")


@manager.command()
@click.option(
    "-m",
    "--mode",
    help="Which file to generate",
    type=Choice(["config", "names"], case_sensitive=False),
    default="config",
)
def codegen(mode="config"):
    """Regenerate configuration or riko/modules/_names.py files"""
    gen_config = mode == "config"
    gen_names = mode == "names"
    return_code = gen_config_main() if gen_config else gen_names_main()

    if gen_config and return_code:
        raise RuntimeError("Error updating configuration file!")
    if gen_names and return_code:
        raise RuntimeError("Error regenerating module names!")
    elif gen_config:
        print("Successfully updated configuration file.")
    elif gen_names:
        print("Successfully regenerated module names.")


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
    check_call(ROOT_DIR / "bin" / "clean")


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


def _twine_check() -> int:
    """Validate built distributions render on PyPI"""
    dists = sorted(glob(str(ROOT_DIR / "dist" / "*")))
    inputs = [ROOT_DIR / "README.rst", ROOT_DIR / "pyproject.toml"]

    if not dists:
        raise RuntimeError("No distributions found in dist/; run `manage build` first")
    elif max(map(getmtime, inputs)) > min(map(getmtime, dists)):
        raise RuntimeError("dist/ is stale; run `manage build` first")
    elif twine:
        cmd = [twine, "check", *dists]
    elif uv:
        cmd = [uv, "run", "--active", "--with", "twine", "twine", "check", *dists]
    else:
        raise RuntimeError("twine not found")

    return call(cmd)


def _check_types() -> int:
    """Check type annotations with pyright"""
    if not pyright:
        raise RuntimeError("pyright not found")

    return call([pyright])


def _verify_types() -> int:
    """Verify type completeness with pyright"""
    if not pyright:
        raise RuntimeError("pyright not found")

    return call([pyright, "--verifytypes", "riko", "--ignoreexternal"])


def _pylint_check(parallel: bool = False) -> int:
    """Check style with pylint"""
    if not pylint:
        raise RuntimeError("pylint not found")

    args = [pylint, "--rcfile=tests/standard.rc", "-rn", "-fparseable", "riko"]

    if parallel:
        args.extend(["-j", "0"])

    return call(args)


def _ruff_check(where: str | None = "", unsafe_fixes: bool = False) -> int:
    """Check style and formatting with ruff"""
    if not ruff:
        raise RuntimeError("ruff not found")

    args = [ruff, "check"]

    if unsafe_fixes:
        args.append("--unsafe-fixes")

    if where:
        args.extend(where.split(" "))

    return call([*args]) or call([ruff, "format", "--check"])


TARGET_RE = re.compile(r"^\.\. _(?P<name>.+?): (?P<uri>\S.*)$", re.MULTILINE)
LINE_ANCHOR_RE = re.compile(r"^L\d")


def _github_slug(text: str) -> str:
    """Convert a heading to its GitHub anchor slug"""
    lowered = text.strip().lower()
    kept = "".join(c for c in lowered if c.isalnum() or c in {" ", "-", "_"})
    return kept.replace(" ", "-")


def _doc_files(where: str | None) -> list[str]:
    """Resolve the RST files to check"""
    if where:
        files = where.split(" ")
    else:
        roots = glob(str(ROOT_DIR / "*.rst"))
        files = sorted(roots + glob(str(ROOT_DIR / "docs" / "*.rst")))

    return files


def _render_rst(path: str) -> tuple[str, Any]:
    """Read and parse an RST file into (source, doctree)"""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    overrides = {
        "report_level": 2,
        "halt_level": 5,
        "warning_stream": StringIO(),
        "input_encoding": "utf-8",
    }
    return text, publish_doctree(text, source_path=path, settings_overrides=overrides)


def _doc_anchors(doctree: Any) -> set[str]:
    """Compute the GitHub heading anchors a rendered doc exposes"""
    seen: dict[str, int] = {}
    anchors: set[str] = set()

    for node in doctree.findall(nodes.title):
        if isinstance(node.parent, (nodes.section, nodes.document)):
            base = _github_slug(node.astext())
            count = seen.get(base, 0)
            anchors.add(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1

    return anchors


def _render_errors(path: str, doctree: Any) -> list[str]:
    """Collect docutils warning/error/severe messages from a rendered doc"""
    return [
        f"{path}:{node.get('line', '?')}: [{node['type']}] {node.children[0].astext()}"
        for node in doctree.findall(nodes.system_message)
        if node["level"] >= 2
    ]


def _anchors_for(path: str, cache: dict[str, set[str]]) -> set[str]:
    """Return the cached anchor set for a doc, rendering it on first use"""
    if path not in cache:
        try:
            cache[path] = _doc_anchors(_render_rst(path)[1])
        except OSError:
            cache[path] = set()

    return cache[path]


def _link_errors(path: str, text: str, cache: dict[str, set[str]]) -> list[str]:
    """Validate internal hyperlink targets resolve to files and anchors"""
    base_dir = dirname(path)
    errors: list[str] = []

    for match in TARGET_RE.finditer(text):
        uri = match["uri"].strip()
        ref_path, _, anchor = uri.partition("#")
        target = join(base_dir, ref_path) if ref_path else path
        external = uri.startswith(("http://", "https://", "mailto:", "//"))

        if external:
            continue
        elif ref_path and not exists(target):
            errors.append(f"{path}: broken target '{uri}' (missing file)")
        elif anchor and not LINE_ANCHOR_RE.match(anchor) and target.endswith(".rst"):
            where = ref_path or basename(path)

            if anchor not in _anchors_for(target, cache):
                errors.append(f"{path}: unknown anchor '#{anchor}' in {where}")

    return errors


def _rst_check(where: str | None = None) -> int:
    """Validate RST rendering and internal links"""
    if publish_doctree is None:
        raise RuntimeError("docutils not found")

    cache: dict[str, set[str]] = {}
    problems: list[str] = []

    for path in _doc_files(where):
        text, doctree = _render_rst(path)
        cache[path] = _doc_anchors(doctree)
        problems.extend(_render_errors(path, doctree))
        problems.extend(_link_errors(path, text, cache))

    for problem in problems:
        print(problem)

    return 1 if problems else 0


@manager.command()
def check():
    """Check staged changes for lint errors"""
    exit(call(ROOT_DIR / "bin" / "check-stage"))


@manager.command()
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
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
def lint(
    paths=(),
    where=(),
    unsafe_fixes=False,
    strict=False,
    check_types=False,
    verify_types=False,
    dist=False,
    rst=False,
    parallel=False,
):
    """Check style with linters"""
    where = " ".join([*where, *paths])

    if dist:
        return_code = _twine_check()
    elif check_types:
        return_code = _check_types()
    elif verify_types:
        return_code = _verify_types()
    elif strict:
        return_code = _pylint_check(parallel)
    elif rst:
        return_code = _rst_check(where)
    else:
        return_code = _ruff_check(where, unsafe_fixes)

    exit(return_code)


@manager.command()
@click.option("-w", "--where", help="Modules to check", default=None)
@click.option("-s", "--sort/--no-sort", help="Sort module imports", default=True)
@click.option("-F", "--unsafe-fixes", help="Applies unsafe fixes", is_flag=True)
def prettify(where=None, sort=True, gen_config=False, unsafe_fixes=False):
    """Prettify code with ruff"""
    where = where or ""
    return_code = 0

    if sort and ruff:
        sort_cmd = [ruff, "check", "--select", "I", "--fix"]
        style_cmd = [ruff, "check", "--fix"]

        if unsafe_fixes:
            style_cmd.append("--unsafe-fixes")

        if where:
            sort_cmd.extend(where.split(" "))
            style_cmd.extend(where.split(" "))

        try:
            check_call(sort_cmd)
            check_call(style_cmd)
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
    "-p",
    "--parallel",
    help="Run tests in parallel in multiple processes",
    is_flag=True,
)
def test(paths=(), where=(), stop=None, **kwargs):  # noqa: PT028
    """Run pytest, tox, and script tests"""
    where = [*where, *paths]

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
        # -s disables capture so the pdb prompt is interactive in the subprocess
        opts += " --pdb -s"

    opts += f" {' '.join(where)}" if where else ""

    try:
        if tox and kwargs.get("tox"):
            runner = ["p"] if kwargs.get("parallel") else ["r"]
            topts = ["-e", tox_env] if (tox_env := kwargs.get("tox_env")) else []
            check_call([tox] + topts + runner)
        elif kwargs.get("tox"):
            raise RuntimeError("tox not found")
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
@click.option("-d", "--dry-run", help="Publish riko to PyPI", is_flag=True)
def publish(dry_run=False):
    """Publish riko to PyPI"""
    try:
        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
@click.option("-d", "--dry-run", help="Build and publish riko to PyPI", is_flag=True)
def release(dry_run=False):
    """Build and publish new riko version"""
    try:
        _clean()
        _build()

        if return_code := _twine_check():
            exit(return_code)

        _publish(dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


if __name__ == "__main__":
    manager()
