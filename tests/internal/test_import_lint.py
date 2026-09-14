from pathlib import Path

from riko.cli._lint_canonical_imports import _iter_issues as canonical_issues
from riko.cli._lint_import_architecture import generate_report, render_architecture
from riko.cli._lint_relative_imports import _iter_issues as relative_issues

# TODO: add tests for:
# ArchitectureReport
# DAG transitive permission
# forbidden direction
# same-layer private target allowed
# same-layer public target forbidden
# local imports enforced
# exact if TYPE_CHECKING exemption
# TYPE_CHECKING else branch runtime
# from . import _private resolution
# mixed allowed/forbidden multi-target statements
# type-only dependency reporting
# unclassified modules
# dangling declaration
# cyclic declaration
# redundant declaration
# deterministic diagnostic order
# CLI exit 0/1/2
# analysis errors


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def test_canonical(tmp_path: Path) -> None:
    root = tmp_path / "riko"
    write(root, "__init__.py", "from .core import Thing\n")
    write(root, "core.py", "class Thing: pass\n")
    write(root, "use.py", "from riko import Thing\n")
    issues = canonical_issues(root)
    assert len(issues) == 1
    assert issues[0].canonical_module == "riko.core"


def test_relative(tmp_path: Path) -> None:
    root = tmp_path / "riko"
    write(root, "__init__.py", "")
    write(root, "pkg/__init__.py", "")
    write(root, "pkg/a.py", "from riko.pkg.b import thing\n")
    write(root, "pkg/b.py", "thing = 1\n")
    issues = relative_issues(root)
    assert len(issues) == 1
    assert issues[0].suggestion == "from .b import thing"


def test_architecture(tmp_path: Path) -> None:
    root = tmp_path / "riko"
    write(root, "__init__.py", "")
    write(root, "types/__init__.py", "")
    write(root, "types/a.py", "from riko.runtime.b import thing\n")
    write(root, "runtime/__init__.py", "")
    write(root, "runtime/b.py", "thing = 1\n")
    report = generate_report(root)
    assert not report.unclassified
    assert len(report.violations) == 1
    assert "types -> {runtime}" in render_architecture(report)


def test_type_checking_is_exempt(tmp_path: Path) -> None:
    root = tmp_path / "riko"
    write(root, "__init__.py", "")
    write(root, "types/__init__.py", "")
    write(
        root,
        "types/a.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from riko.runtime.b import thing\n",
    )
    write(root, "runtime/__init__.py", "")
    write(root, "runtime/b.py", "thing = 1\n")
    assert not generate_report(root).violations


def test_unclassified_fails(tmp_path: Path) -> None:
    root = tmp_path / "riko"
    write(root, "__init__.py", "")
    write(root, "mystery/__init__.py", "")
    report = generate_report(root)
    assert report.unclassified[0].module == "riko.mystery"
