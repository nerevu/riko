# vim: sw=4:ts=4:expandtab
"""
Tests that generated Objconf types match their Conf definitions.

Run ``manage codegen -m config`` to update generated configs.
"""

import pathlib

from riko.cli._gen_config import objconf_structure, render

_CONFIGS = pathlib.Path("riko/coercion/_configs.py")


def test_configs_match_generated():
    assert _CONFIGS.read_text() == render()


def test_fetchtable_inherits_csv():
    assert objconf_structure()["FetchTableObjconf"][0] == "CsvObjconf"
