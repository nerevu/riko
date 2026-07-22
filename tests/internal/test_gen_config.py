# vim: sw=4:ts=4:expandtab
"""
Guard that riko/types/configs.py stays in sync with the nonraw Conf contracts.

The ``<Name>Objconf`` types are generated from the ``<Name>Conf`` TypedDicts in
``riko.types.modules`` (see ``riko.cli.gen_config``). This asserts the committed
``configs.py`` matches what the generator would produce — structurally, so quoting
and formatting differences from ``ruff format`` don't cause false failures. Run
``gen-config`` to fix a real drift.
"""

import ast
import pathlib

from riko.cli.gen_config import _own_fields, objconf_structure

_CONFIGS = pathlib.Path("riko/types/configs.py")


def _committed_structure() -> dict[str, tuple[str, dict[str, str]]]:
    tree = ast.parse(_CONFIGS.read_text())
    structure = {
        node.name: (
            next((b.id for b in node.bases if isinstance(b, ast.Name)), ""),
            _own_fields(node),
        )
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Objconf")
    }
    return structure


def test_configs_match_generated():
    assert _committed_structure() == objconf_structure()


def test_every_objconf_has_nonraw_source():
    generated = set(objconf_structure())
    committed = set(_committed_structure())
    assert committed == generated


def test_fetchtable_inherits_csv():
    assert objconf_structure()["FetchTableObjconf"][0] == "CsvObjconf"
