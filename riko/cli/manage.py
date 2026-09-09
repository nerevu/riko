# vim: sw=4:ts=4:expandtab

"""A script to manage development tasks"""

import re
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from glob import glob
from io import StringIO
from itertools import chain
from os import environ
from os.path import basename, dirname, exists, getmtime, isdir, join
from pathlib import Path
from subprocess import CalledProcessError, call, check_call, check_output
from sys import exit
from typing import Any, NamedTuple

import click
import requests
from click import Choice

from riko._logging import exception_hook
from riko.cli.gen_config import _CONFIGS as CONFIG_PATH
from riko.cli.gen_config import main as gen_config_main
from riko.cli.gen_names import _MODULE_IDS as MODULE_IDS_PATH
from riko.cli.gen_names import _NAMES as NAMES_PATH
from riko.cli.gen_names import main as gen_names_main
from riko.cli.gen_pipelines import main as gen_pipelines_main
from riko.paths import ROOT_DIR

try:
    from docutils import nodes
    from docutils.core import publish_doctree
except ImportError:
    publish_doctree = None
    nodes = None

sys.excepthook = partial(exception_hook, debug=False)

TARGET_RE = re.compile(r"^\.\. _(?P<name>.+?): (?P<uri>\S.*)$", re.MULTILINE)
LINE_ANCHOR_RE = re.compile(r"^L\d")
DOCS_DIR = ROOT_DIR / "docs"
WORKFLOW_DIR = ROOT_DIR / ".github" / "workflows"
CHANGELOG_PATH = DOCS_DIR / "CHANGES.rst"
GITHUB_REPO = "nerevu/riko"
PYPI_PROJECT = "riko"

RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
RELEASE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
RST_SUBHEADING_RE = re.compile(r"^(?P<title>[^\n]+)\n~+$", re.MULTILINE)
RELEASE_SECTION_RE = re.compile(
    r"^(?P<version>v\d+\.\d+\.\d+) \((?P<release_date>[^)]+)\)\n-+\n\n"
    r"(?P<body>.*?)"
    r"(?=^v\d+\.\d+\.\d+ \([^)]+\)\n-+\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


class Entry(NamedTuple):
    version: str
    release_date: str
    body: str


CODEGEN: dict[str, tuple[Callable[[], int], Callable[[], str], str]] = {
    "config": (
        gen_config_main,
        lambda: f"wrote configuration file to {CONFIG_PATH}",
        "Error updating configuration file!",
    ),
    "names": (
        gen_names_main,
        lambda: f"regenerated module names to {NAMES_PATH} and {MODULE_IDS_PATH}",
        "Error regenerating module names!",
    ),
    "pipes": (
        gen_pipelines_main,
        lambda: "regenerated compiled pipe modules from their JSON definitions",
        "Error regenerating compiled pipe modules!",
    ),
}


uv: str | None = shutil.which("uv")
tox: str | None = shutil.which("tox")
pytest: str | None = shutil.which("pytest")
ruff: str | None = shutil.which("ruff")
pylint: str | None = shutil.which("pylint")
pyright: str | None = shutil.which("pyright")
twine: str | None = shutil.which("twine")
actionlint: str | None = shutil.which("actionlint")
shellcheck: str | None = shutil.which("shellcheck")
yamlfmt: str | None = shutil.which("yamlfmt")
gh: str | None = shutil.which("gh")


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
@click.pass_context
def help(ctx):
    """Show available commands"""
    commands = "\n  ".join(manager.list_commands(ctx))
    print("Usage: manage <command> [OPTIONS]")
    print("commands:")
    print(f"  {commands}")


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------
def _clean():
    """Remove Python file and build artifacts"""
    for name in ("dist", "build"):
        shutil.rmtree(ROOT_DIR / name, ignore_errors=True)

    for pattern in ("*.egg-info", "src/*.egg-info"):
        for path in glob(str(ROOT_DIR / pattern)):
            shutil.rmtree(path, ignore_errors=True)

    for pattern in ("*.pyc", "*.pyo", "*~"):
        for path in ROOT_DIR.rglob(pattern):
            path.unlink(missing_ok=True)


def _build():
    """Build riko package"""
    if uv:
        check_call([uv, "build"])
    else:
        raise RuntimeError("uv not found")


def _publish(dry_run=False):
    """Publish riko to PyPI"""
    cmd = ["publish", "--dry-run"] if dry_run else ["publish"]

    if uv:
        check_call([uv, *cmd])
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


# ---------------------------------------------------------------------------
# Lint helpers
# ---------------------------------------------------------------------------
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

    paths = where.split(" ") if where else []
    args = [ruff, "check"]

    if unsafe_fixes:
        args.append("--unsafe-fixes")

    return call([*args, *paths]) or call([ruff, "format", "--check", *paths])


def _slugify(text: str) -> str:
    r"""
    Convert a heading to its GitHub anchor slug

    TODO: Update meza and replace with
    slugify(text, allow_unicode=True, regex_pattern=r"[^\w-]+")
    """
    lowered = text.strip().lower()
    kept = "".join(c for c in lowered if c.isalnum() or c in {" ", "-", "_"})
    return kept.replace(" ", "-")


def _gen_doc_files(where: str | None) -> Iterator[str]:
    """Resolve the RST files to check"""
    for location in where.split(" ") if where else [ROOT_DIR, DOCS_DIR]:
        if isdir(location):
            yield from glob(str(Path(location) / "*.rst"))
        elif Path(location).suffix == ".rst":
            yield str(location)


def _gen_yaml_files() -> Iterator[str]:
    """Return tracked YAML files."""
    args = ["git", "ls-files", "*.yml", "*.yaml"]
    yield from check_output(args, text=True).splitlines()


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


def _get_doc_anchors(doctree: Any) -> set[str]:
    """Compute the GitHub heading anchors a rendered doc exposes"""
    seen: dict[str, int] = {}
    anchors: set[str] = set()

    for node in doctree.findall(nodes.title):
        if isinstance(node.parent, (nodes.section, nodes.document)):
            base = _slugify(node.astext())
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


def _get_path_anchors(path: str, cache: dict[str, set[str]]) -> set[str]:
    """Return the cached anchor set for a doc, rendering it on first use"""
    if path not in cache:
        try:
            cache[path] = _get_doc_anchors(_render_rst(path)[1])
        except OSError:
            cache[path] = set()

    return cache[path]


def _get_staged() -> list[str]:
    """List staged Python files (added/copied/modified, not deleted)"""
    args = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    staged = check_output(args, text=True).splitlines()
    return [name for name in staged if name.endswith(".py")]


def _check_links(path: str, text: str, cache: dict[str, set[str]]) -> list[str]:
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

            if anchor not in _get_path_anchors(target, cache):
                errors.append(f"{path}: unknown anchor '#{anchor}' in {where}")

    return errors


def _check_rst(where: str | None = None) -> int:
    """Validate RST rendering and internal links"""
    if publish_doctree is None:
        raise RuntimeError("docutils not found")

    cache: dict[str, set[str]] = {}
    problems: list[str] = []

    for path in _gen_doc_files(where):
        text, doctree = _render_rst(path)
        cache[path] = _get_doc_anchors(doctree)
        problems.extend(_render_errors(path, doctree))
        problems.extend(_check_links(path, text, cache))

    for problem in problems:
        print(problem)

    return 1 if problems else 0


def _check_actions(where: Iterable[str]) -> int:
    """Validate GitHub Actions workflows with actionlint and shellcheck."""
    if not actionlint:
        raise RuntimeError("actionlint not found")
    elif not shellcheck:
        raise RuntimeError("shellcheck not found")

    return call([actionlint, *where])


def _check_yaml(where: Iterable[str] = ()) -> int:
    """Link YAML files with yamlfmt."""
    if not yamlfmt:
        raise RuntimeError("yamlfmt not found")

    paths = where or _gen_yaml_files()
    return call([yamlfmt, "-lint", *paths])


def _check_staged() -> int:
    """Lint staged Python files with ruff"""
    if not ruff:
        raise RuntimeError("ruff not found")

    files = _get_staged()

    if not files:
        return_code = 0
    else:
        return_code = call([ruff, "check", *files]) or call(
            [ruff, "format", "--check", *files]
        )

    return return_code


# ---------------------------------------------------------------------------
# Prettify helpers
# ---------------------------------------------------------------------------
def _format_yaml(where: Iterable[str] = ()) -> int:
    """Format YAML files with yamlfmt."""
    if not yamlfmt:
        raise RuntimeError("yamlfmt not found")

    paths = where or _gen_yaml_files()
    return call([yamlfmt, *paths])


# ---------------------------------------------------------------------------
# Release helpers
# ---------------------------------------------------------------------------
def _gen_changelog_entries(path: Path = CHANGELOG_PATH) -> Iterator[Entry]:
    """Return changelog entries in document order."""
    text = path.read_text(encoding="utf-8")

    for match in RELEASE_SECTION_RE.finditer(text):
        yield Entry(match["version"], match["release_date"], match["body"].strip())


def _get_changelog_entry(
    version: str | None = None, path: Path = CHANGELOG_PATH
) -> Entry:
    """Return a changelog version, release date, and RST body."""
    for entry in _gen_changelog_entries(path):
        if (version is None) or entry.version == version:
            return entry

    if version:
        msg = f"No changelog entry found for {version} in {path}"
    else:
        msg = f"No release section found in {path}"

    raise RuntimeError(msg)


def _validate_tag(version: str, *expected: str) -> None:
    """Validate a release version and optional expected tag."""
    if not RELEASE_TAG_RE.fullmatch(version):
        raise RuntimeError(f"Invalid release tag {version!r}")

    if expected and version not in expected:
        raise RuntimeError(f"{version=} does not exist in {expected=}")


def _gen_gh_tags(releases=False) -> Iterator[str]:
    """Return remote tags."""
    if not gh:
        raise RuntimeError("gh not found")

    param, field = ("releases", "tag_name") if releases else ("tags", "name")
    url = f"repos/{GITHUB_REPO}/{param}?per_page=100"
    args = [gh, "api", "--paginate", "--jq", f".[].{field}", url]
    output = check_output(args, text=True)

    for tag in output.splitlines():
        if RELEASE_TAG_RE.fullmatch(tag):
            yield tag


def _gen_pypi_tags() -> Iterator[str]:
    """Yield versions already published to PyPI as release tags."""
    url = f"https://pypi.org/pypi/{PYPI_PROJECT}/json"
    r = requests.get(url, timeout=15)

    if r.ok:
        for tag in r.json()["releases"]:
            if RELEASE_VERSION_RE.fullmatch(tag):
                yield f"v{tag}"


def _gen_missing_versions(published: Iterable[str]) -> Iterator[str]:
    """Return remote release tags absent from published."""
    missing = set(_gen_gh_tags()).difference(published)
    _release_key = lambda version: tuple(map(int, version.removeprefix("v").split(".")))
    yield from sorted(missing, key=_release_key)


def _dispatch_workflow(
    workflow: str, dry_run: bool = False, **fields: str | bool
) -> None:
    """Dispatch a workflow from the current main branch."""
    if not gh:
        raise RuntimeError("gh not found")

    args = [gh, "workflow", "run", workflow, "--repo", GITHUB_REPO, "--ref", "main"]

    for key, value in fields.items():
        rendered = str(value).lower() if isinstance(value, bool) else value
        args.extend(["-f", f"{key}={rendered}"])

    if dry_run:
        click.echo(f"[dry-run] would dispatch: {' '.join(args)}")
    else:
        check_call(args)


def _backfill_github(
    version: str, notes_only: bool = False, dry_run: bool = False
) -> None:
    """Dispatch GitHub release creation or release-note repair."""
    _validate_tag(version, *_gen_gh_tags())
    entry = _get_changelog_entry(version)

    if entry.release_date == "Unreleased":
        raise RuntimeError(f"Changelog entry for {version} is unreleased")

    exists = version in set(_gen_gh_tags(releases=True))
    msg = f"GitHub release {version}"

    if notes_only and not exists:
        msg += " does not exist. Run without --notes-only to create it"
        raise RuntimeError(msg)
    elif not notes_only and exists:
        msg += " already exists. Use --notes-only to replace its notes"
        raise RuntimeError(msg)

    _dispatch_workflow(
        "release.yml", dry_run=dry_run, tag=version, notes_only=notes_only
    )


def _backfill_pypi(version: str, dry_run: bool = False) -> None:
    """Dispatch publication of an existing tag to PyPI."""
    _validate_tag(version, *_gen_gh_tags())

    if version in set(_gen_pypi_tags()):
        raise RuntimeError(f"{PYPI_PROJECT} {version} already exists on PyPI")

    _dispatch_workflow("publish.yml", dry_run=dry_run, tag=version)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@manager.command()
def check():
    """Lint staged Python changes with ruff"""
    exit(_check_staged())


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
@click.option("-a", "--actions", help="Validate GitHub Actions workflows", is_flag=True)
@click.option("-y", "--yaml", help="Validate YAML files", is_flag=True)
@click.option(
    "-p",
    "--parallel",
    help="Run linter in parallel in multiple processes",
    is_flag=True,
)
def lint(
    paths: tuple[str, ...] = (),
    where: tuple[str, ...] = (),
    unsafe_fixes=False,
    strict=False,
    check_types=False,
    verify_types=False,
    dist=False,
    rst=False,
    actions=False,
    yaml=False,
    parallel=False,
):
    """Check style with linters"""
    _where = " ".join([*where, *paths])

    if dist:
        return_code = _twine_check()
    elif check_types:
        return_code = _check_types()
    elif verify_types:
        return_code = _verify_types()
    elif strict:
        return_code = _pylint_check(parallel)
    elif rst:
        return_code = _check_rst(_where)
    elif actions:
        exts = [".yml", ".yaml"]
        _paths = (glob(str(WORKFLOW_DIR / f"*.{ext}")) for ext in exts)
        return_code = _check_actions(chain.from_iterable(_paths))
    elif yaml:
        return_code = _check_yaml(_where)
    else:
        return_code = _ruff_check(_where, unsafe_fixes)

    exit(return_code)


@manager.command()
@click.option("-w", "--where", help="Modules to check", multiple=True)
@click.option("-s", "--sort/--no-sort", help="Sort module imports", default=True)
@click.option("-y", "--yaml", help="Format YAML files", is_flag=True)
@click.option("-F", "--unsafe-fixes", help="Applies unsafe fixes", is_flag=True)
def prettify(
    where: tuple[str, ...] = (),
    sort=True,
    yaml=False,
    gen_config=False,
    unsafe_fixes=False,
):
    """Prettify code with ruff"""
    return_code = 0

    if yaml:
        return_code = _format_yaml(where)
    elif sort and ruff:
        sort_cmd = [ruff, "check", "--select", "I", "--fix"]
        style_cmd = [ruff, "check", "--fix"]

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

    if ruff and not return_code:
        cmd = [ruff, "format"]

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
    "-p", "--parallel", help="Run tests in parallel in multiple processes", is_flag=True
)
def test(
    paths: tuple[str, ...] = (),  # noqa: PT028
    where: tuple[str, ...] = (),  # noqa: PT028
    stop=None,  # noqa: PT028
    **kwargs,
):
    """Run pytest, tox, and script tests"""
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
        # -s disables capture so the pdb prompt is interactive in the subprocess
        opts += " --pdb -s"

    opts += f" {' '.join(_where)}" if _where else ""

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
@click.option(
    "-m",
    "--mode",
    help="Which file to generate",
    type=Choice(list(CODEGEN), case_sensitive=False),
    default="config",
)
def codegen(mode="config"):
    """Regenerate config, module-name, or compiled-pipe files"""
    runner, summary, error = CODEGEN[mode]

    if runner():
        raise RuntimeError(error)

    print(f"Successfully {summary()}.")


@manager.command("release-notes")
@click.argument("version", required=False)
def release_notes(version: str | None = None):
    """Convert a changelog section to Markdown release notes."""
    entry = _get_changelog_entry(version)

    if environ.get("GITHUB_REF_TYPE") == "tag":
        _validate_tag(entry.version, environ.get("GITHUB_REF_NAME", ""))

    if environ.get("GITHUB_ACTIONS") and entry.release_date == "Unreleased":
        raise RuntimeError(f"Changelog entry for {entry.version} is unreleased")

    click.echo(RST_SUBHEADING_RE.sub(r"### \g<title>", entry.body))


@manager.command()
@click.argument(
    "targets", nargs=-1, type=Choice(["github", "pypi"], case_sensitive=False)
)
def missing(targets: tuple[str, ...] = ()):
    """List release versions missing from publication targets."""
    targets = targets or ("github", "pypi")
    missing_by_target = {"github": partial(_gen_gh_tags, True), "pypi": _gen_pypi_tags}
    multiple = len(targets) > 1

    for target in targets:
        tags = missing_by_target[target]()
        versions = _gen_missing_versions(tags)

        if multiple:
            click.echo(f"{target}:")

        for version in versions:
            click.echo(version)


@manager.command()
@click.argument("target", type=Choice(["github", "pypi"], case_sensitive=False))
@click.argument("version")
@click.option(
    "--notes-only", help="Replace notes on an existing GitHub release", is_flag=True
)
@click.option(
    "-d",
    "--dry-run",
    help="Show the workflow dispatch without triggering it",
    is_flag=True,
)
def backfill(
    target: str, version: str, notes_only: bool = False, dry_run: bool = False
):
    """Backfill an incomplete historical release."""
    is_github = target == "github"

    if notes_only and not is_github:
        raise click.UsageError("--notes-only is only valid for GitHub releases")

    try:
        if is_github:
            _backfill_github(version, notes_only, dry_run)
        else:
            _backfill_pypi(version, dry_run)
    except CalledProcessError as e:
        exit(e.returncode)


@manager.command()
def clean():
    """Remove Python file and build artifacts"""
    _clean()


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
    help="Rehearse the upload without publishing to PyPI",
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
    help="Build, check, and rehearse the upload without publishing",
    is_flag=True,
)
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
