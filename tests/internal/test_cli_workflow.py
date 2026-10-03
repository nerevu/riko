# vim: sw=4:ts=4:expandtab

"""Tests the shared workflow document front door the console scripts read through."""

from __future__ import annotations

import json

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.cli._workflow import (
    DocumentFormat,
    get_document_format,
    normalize_document,
    read_document,
    require_workflow,
)
from riko.runtime._migrate import migrate_v1_to_v2, parse_dag
from riko.runtime._normalize import normalize_workflow
from riko.runtime._serialize import serialize_workflow
from tests import TESTS_DIR

DAG_PATH = TESTS_DIR / "dags" / "pipe_forever.json"
DAG = json.loads(DAG_PATH.read_text(encoding="utf-8"))
PIPE_DEF = {
    "modules": [
        {"id": "sw-1", "type": "forever", "conf": {}},
        {"id": "_OUTPUT", "type": "output", "conf": {}},
    ],
    "wires": [
        {
            "id": "_w1",
            "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
            "tgt": {"id": "_INPUT", "moduleid": "_OUTPUT"},
        }
    ],
}
RAW_WORKFLOW = {"nodes": [{"name": "forever"}]}
WORKFLOW = json.loads(serialize_workflow(parse_dag(DAG)))
DOCUMENTS = [
    pytest.param(DAG, DocumentFormat.DAG, parse_dag, id="dag"),
    pytest.param(PIPE_DEF, DocumentFormat.V1, migrate_v1_to_v2, id="v1"),
    pytest.param(RAW_WORKFLOW, DocumentFormat.V2, normalize_workflow, id="v2"),
    pytest.param(WORKFLOW, DocumentFormat.V2, normalize_workflow, id="workflow"),
]
LEGACY = [pytest.param(DAG, id="dag"), pytest.param(PIPE_DEF, id="v1")]


@pytest.mark.parametrize(("document", "fmt", "loader"), DOCUMENTS)
def test_get_document_format(document, fmt, loader):
    """Each readable document shape is recognized from its own structure."""
    assert get_document_format(document) is fmt


@pytest.mark.parametrize(("document", "fmt", "loader"), DOCUMENTS)
def test_load_workflow_matches_loader(document, fmt, loader):
    """Loading a document yields what its own loader yields."""
    assert normalize_document(document) == loader(document)


def test_get_document_format_rejects_unknown_shape():
    with pytest.raises(InvalidPipelineError, match="'nodes' or 'modules'"):
        get_document_format({"pipeline": []})


def test_load_workflow_honors_the_declared_format():
    """A document read as a shape it is not written in is rejected, not guessed."""
    with pytest.raises(InvalidPipelineError):
        normalize_document(DAG, DocumentFormat.V2)


@pytest.mark.parametrize("document", LEGACY)
def test_require_workflow_points_at_the_converter(document):
    with pytest.raises(InvalidPipelineError, match="build-workflow"):
        require_workflow(document)


def test_require_workflow_accepts_a_canonical_document():
    assert require_workflow(WORKFLOW) == parse_dag(DAG)


def test_read_document_reports_a_missing_path():
    assert read_document("no-such-flow.json") == (None, "no-such-flow")


def test_read_document_parses_a_committed_document():
    document, name = read_document(str(DAG_PATH))
    assert (document, name) == (DAG, "pipe_forever")


def test_load_workflow_rejects_an_empty_dag():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        normalize_document({"modules": []})
