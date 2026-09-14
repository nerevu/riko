from pathlib import Path

from riko.cli._lint_canonical_imports import _iter_issues as canonical_issues
from riko.cli._lint_import_architecture import _architecture, _render_architecture
from riko.cli._lint_relative_imports import _iter_issues as relative_issues


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
    _, issues, unclassified = _architecture(root)
    assert not unclassified
    assert len(issues) == 1
    assert "types -> runtime" in _render_architecture(root)


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
    _, issues, _ = _architecture(root)
    assert not issues


def test_unclassified_fails(tmp_path: Path) -> None:
    root = tmp_path / "riko"
    write(root, "__init__.py", "")
    write(root, "mystery/__init__.py", "")
    _, _, unclassified = _architecture(root)
    assert unclassified == ("riko.mystery",)
