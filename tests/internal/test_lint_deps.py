"""Tests for the declared-dependencies lint check."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from riko.cli._lint_deps import (
    gen_dependency_issues,
    gen_hook_pin_issues,
    gen_import_sites,
    get_locked_version,
)
from riko.cli._upgrade import _pin_hooks

if TYPE_CHECKING:
    from pathlib import Path

DISTRIBUTIONS = {
    "dateutil": ["python-dateutil"],
    "lxml": ["lxml"],
    "requests": ["requests"],
    "typing_extensions": ["typing_extensions"],
}

PYPROJECT = """
[project]
dependencies = ["python-dateutil>=2", "requests"]

[project.optional-dependencies]
perf = ["lxml"]

[dependency-groups]
lint = ["types-requests", {include-group = "test"}]
"""


def _issues(tmp_path: Path, source: str, pyproject: str = PYPROJECT) -> list[str]:
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "mod.py").write_text(source, encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(pyproject, encoding="utf-8")
    issues = gen_dependency_issues(package, config, DISTRIBUTIONS)
    return [issue.message for issue in issues]


def test_import_sites_record_their_guard(tmp_path: Path) -> None:
    """Each third-party import is tagged by the strongest statement guarding it."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "mod.py").write_text(
        "import os\n"
        "import requests\n"
        "from . import sibling\n"
        "try:\n"
        "    import lxml\n"
        "except ImportError:\n"
        "    pass\n"
        "if TYPE_CHECKING:\n"
        "    try:\n"
        "        import dateutil\n"
        "    except ImportError:\n"
        "        pass\n",
        encoding="utf-8",
    )
    sites = [(site.name, site.guard) for site in gen_import_sites(package)]
    expected = [("requests", "none"), ("lxml", "try"), ("dateutil", "type_checking")]
    assert sites == expected


def test_unguarded_import_must_be_a_project_dependency(tmp_path: Path) -> None:
    """An import that always runs needs a required dependency, not a transitive one."""
    source = "import requests\nfrom dateutil import parser\nimport typing_extensions\n"
    expected = [
        "'typing_extensions' is imported unguarded but is not a [project] dependency"
    ]
    assert _issues(tmp_path, source) == expected


def test_function_local_import_counts_as_unguarded(tmp_path: Path) -> None:
    """A function-local import still needs its package whenever the function runs."""
    source = (
        "import requests\nimport dateutil\ndef f():\n    import typing_extensions\n"
    )
    expected = [
        "'typing_extensions' is imported unguarded but is not a [project] dependency"
    ]
    assert _issues(tmp_path, source) == expected


def test_try_import_may_come_from_any_declaration(tmp_path: Path) -> None:
    """An optional import is fine from an extra but not from nowhere."""
    source = (
        "import requests\n"
        "import dateutil\n"
        "try:\n"
        "    import lxml\n"
        "    import ujson\n"
        "except ImportError:\n"
        "    pass\n"
    )
    expected = ["'ujson' is imported in a try block but declared nowhere"]
    assert _issues(tmp_path, source) == expected


def test_type_checking_import_neither_needs_nor_satisfies_a_dependency(
    tmp_path: Path,
) -> None:
    """A type-only import never needs or justifies a runtime dependency."""
    source = (
        "import requests\n"
        "if TYPE_CHECKING:\n"
        "    import dateutil\n"
        "    import typing_extensions\n"
    )
    expected = ["'python-dateutil' is a [project] dependency that nothing imports"]
    assert _issues(tmp_path, source) == expected


def test_stub_package_must_not_be_a_runtime_requirement(tmp_path: Path) -> None:
    """A ``types-*`` stub in an extra is flagged; one in a dependency group is not."""
    source = "import requests\nimport dateutil\n"
    expected = ["'types-lxml' is a typing stub; declare it in a dependency group"]
    pyproject = PYPROJECT.replace('perf = ["lxml"]', 'perf = ["lxml", "types-lxml"]')
    assert _issues(tmp_path, source) == []
    assert _issues(tmp_path, source, pyproject) == expected


def test_uninstalled_module_matches_its_own_distribution_name(tmp_path: Path) -> None:
    """An uninstalled extra still matches the declaration it shares a name with."""
    source = (
        "import requests\n"
        "import dateutil\n"
        "try:\n"
        "    import httpx\n"
        "except ImportError:\n"
        "    pass\n"
    )
    pyproject = PYPROJECT.replace('perf = ["lxml"]', 'perf = ["httpx"]')
    assert _issues(tmp_path, source, pyproject) == []


LOCK = """
[[package]]
name = "ruff"
version = "0.16.10"
"""

HOOKS = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        additional_dependencies: [ruff==0.16.10]
      - id: ruff-format
        additional_dependencies: [ruff==0.16.9]
"""


def _pin_issues(tmp_path: Path, hooks: str) -> list[tuple[str, str]]:
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(hooks, encoding="utf-8")
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text(LOCK, encoding="utf-8")
    issues = gen_hook_pin_issues(config, lockfile)
    return [(issue.where.rsplit(":", 1)[-1], issue.message) for issue in issues]


def test_hook_pin_must_match_the_lock(tmp_path: Path) -> None:
    """A hook that pins another ruff than uv.lock is reported at its line."""
    expected = [("8", "hook pins ruff==0.16.9 but uv.lock has 0.16.10")]
    assert _pin_issues(tmp_path, HOOKS) == expected


def test_hooks_must_pin_each_locked_tool(tmp_path: Path) -> None:
    """A configuration that never pins ruff is reported."""
    hooks = "repos: []\n"
    found = [message for _, message in _pin_issues(tmp_path, hooks)]
    assert found == ["no hook pins 'ruff'; pin it as ruff==0.16.10"]


def test_upgrade_rewrites_hook_pins_to_the_lock(tmp_path: Path) -> None:
    """After an upgrade, every hook pin names the locked version."""
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(HOOKS, encoding="utf-8")
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text(LOCK, encoding="utf-8")
    _pin_hooks(config, lockfile)
    assert list(gen_hook_pin_issues(config, lockfile)) == []
    assert config.read_text(encoding="utf-8").count("ruff==0.16.10") == 2


def test_locked_version_lookup_names_a_missing_package(tmp_path: Path) -> None:
    """Asking the lock for a package it lacks raises instead of guessing."""
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text(LOCK, encoding="utf-8")
    assert get_locked_version(lockfile, "Ruff") == "0.16.10"

    with pytest.raises(LookupError, match="'pyright' is not in"):
        get_locked_version(lockfile, "pyright")
