# vim: sw=4:ts=4:expandtab
"""
riko.cli.gen_config
~~~~~~~~~~~~~~~~~~~~~~
Generator and drift guard for :mod:`riko.types.configs`. The parse-time
``<Name>Objconf`` types are derived from the nonraw ``<Name>Conf`` TypedDict
contracts in :mod:`riko.types.modules`: strip ``Required``/``NotRequired`` and the
``= default`` doc-hints, dereference forward-ref strings, and rebase onto
``DynamicConf`` (or the parent ``*Objconf`` when the source Conf inherits another).

``objconf_structure`` returns the canonical mapping both ``render`` (to emit the
file) and ``tests`` (to assert no drift) build on.
"""

from __future__ import annotations

import ast
import pathlib
import shutil
import subprocess

_TYPES_DIR = pathlib.Path(__file__).parent.parent / "types"
_MODULES = _TYPES_DIR / "modules.py"
_CONFIGS = _TYPES_DIR / "configs.py"
_CAST_TYPES = {"CastType", "LocationType"}
_TYPING_TYPES = {"Any", "Literal"}
_ABC_TYPES = {"Callable", "Sequence"}
_BUILTINS = {"str", "int", "float", "bool", "list", "dict", "tuple", "set", "None"}
_DOCSTRING = '''# vim: sw=4:ts=4:expandtab
"""
riko.types.configs
~~~~~~~~~~~~~~~~~~~
Parse-time ``objconf`` config types, one per module. Each subclasses
``DynamicConf`` (case-insensitive attribute + mapping access; missing keys return
``None``). Field types only — the ``conf=`` contract and its defaults live on the
``<Name>Conf`` TypedDicts in ``riko.types.modules``; runtime defaults come from each
module's ``DEFAULTS``.

Generated from the nonraw ``<Name>Conf`` TypedDicts by ``riko.cli.gen_config``.
Edit those objects (not this file), then regenerate with ``gen-config``.
``tests/internal/test_gen_config.py`` fails if the two layers drift.
"""'''


class _Deref(ast.NodeTransformer):
    def __init__(self):
        self.in_literal = 0

    def visit_Subscript(self, node):
        is_literal = isinstance(node.value, ast.Name) and node.value.id == "Literal"
        node.value = self.visit(node.value)
        self.in_literal += is_literal
        node.slice = self.visit(node.slice)
        self.in_literal -= is_literal
        return node

    def visit_Constant(self, node):
        if self.in_literal == 0 and isinstance(node.value, str):
            result = ast.Name(id=node.value, ctx=ast.Load())
        else:
            result = node

        return result


def _strip_required(annotation):
    wrapped = (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id in {"Required", "NotRequired"}
    )
    return annotation.slice if wrapped else annotation


def _normalize(annotation) -> str:
    inner = _strip_required(annotation)
    module = ast.parse("")
    module.body = [ast.Expr(value=inner)]
    return ast.unparse(_Deref().visit(ast.fix_missing_locations(module)))


def _own_fields(node: ast.ClassDef) -> dict[str, str]:
    return {
        stmt.target.id: _normalize(stmt.annotation)
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    }


def _base(node: ast.ClassDef) -> str:
    parents = [b.id for b in node.bases if isinstance(b, ast.Name)]
    conf_parents = [p for p in parents if p.endswith("Conf")]
    return f"{conf_parents[0][:-4]}Objconf" if conf_parents else "DynamicConf"


def _nonraw_confs() -> list[ast.ClassDef]:
    tree = ast.parse(_MODULES.read_text())
    return [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name.endswith("Conf")
        and not node.name.endswith("RawConf")
    ]


def objconf_structure() -> dict[str, tuple[str, dict[str, str]]]:
    return {
        f"{node.name[:-4]}Objconf": (_base(node), _own_fields(node))
        for node in _nonraw_confs()
    }


def _referenced_names(structure) -> set[str]:
    return {
        name.id
        for _, fields in structure.values()
        for annotation in fields.values()
        for name in ast.walk(ast.parse(annotation))
        if isinstance(name, ast.Name)
    }


def _import_block(structure) -> str:
    referenced = _referenced_names(structure)
    abc = sorted(_ABC_TYPES & referenced)
    typing = ["TYPE_CHECKING", *sorted(_TYPING_TYPES & referenced)]
    cast = sorted(_CAST_TYPES & referenced)
    modules = sorted(
        referenced
        - _CAST_TYPES
        - _TYPING_TYPES
        - _ABC_TYPES
        - _BUILTINS
        - {"DynamicConf"}
    )
    lines = ["from __future__ import annotations", ""]
    lines += [f"from collections.abc import {', '.join(abc)}"] if abc else []
    lines += [
        f"from typing import {', '.join(typing)}",
        "",
        "from riko import DynamicConf",
    ]
    guarded = ["", "if TYPE_CHECKING:"]
    guarded += [f"    from riko.cast import {', '.join(cast)}"] if cast else []

    if modules:
        guarded += ["    from riko.types.modules import ("]
        guarded += [f"        {name}," for name in modules]
        guarded += ["    )"]

    return "\n".join(lines + guarded)


def _class_block(name: str, base: str, fields: dict[str, str]) -> str:
    header = f"class {name}({base}):"
    rendered = [
        f"    {field}: {annotation}"
        + ("  # noqa: N815" if any(c.isupper() for c in field) else "")
        for field, annotation in fields.items()
    ]
    body = rendered or ["    pass"]
    return "\n".join([header, *body])


def render() -> str:
    structure = objconf_structure()
    blocks = [
        _class_block(name, base, fields) for name, (base, fields) in structure.items()
    ]
    parts = [_DOCSTRING, "", _import_block(structure), "", "", "\n\n\n".join(blocks)]
    return "\n".join(parts) + "\n"


def main() -> int:
    _CONFIGS.write_text(render())
    ruff = shutil.which("ruff")
    formatted = ruff and subprocess.run(
        [ruff, "format", str(_CONFIGS)], capture_output=True, text=True, check=False
    )
    return formatted.returncode if formatted else 0


if __name__ == "__main__":
    raise SystemExit(main())
