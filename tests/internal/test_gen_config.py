# vim: sw=4:ts=4:expandtab
"""
Tests that generated Objconf types match their Conf definitions.

Run ``gen-config`` to update generated configs.
"""

import ast
import pathlib

from riko.cli.gen_config import objconf_structure, own_fields, render

_CONFIGS = pathlib.Path("riko/types/configs.py")


def _committed_structure() -> dict[str, tuple[str, dict[str, str]]]:
    tree = ast.parse(_CONFIGS.read_text())
    structure = {
        node.name: (
            next((b.id for b in node.bases if isinstance(b, ast.Name)), ""),
            own_fields(node),
        )
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Objconf")
    }
    return structure


def test_configs_match_generated():
    assert _CONFIGS.read_text() == render()


def test_configs_structure_matches_generated():
    assert _committed_structure() == objconf_structure()


def test_every_objconf_has_nonraw_source():
    generated = set(objconf_structure())
    committed = set(_committed_structure())
    assert committed == generated


def test_fetchtable_inherits_csv():
    assert objconf_structure()["FetchTableObjconf"][0] == "CsvObjconf"
