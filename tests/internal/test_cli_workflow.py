# vim: sw=4:ts=4:expandtab

"""Tests the shared front door that reads each document shape into a ``Workflow``."""

from __future__ import annotations

import io
import json

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.cli import _workflow
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


def _record_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warnings: list[str] = []
    warning = lambda msg, *args: warnings.append(msg % args)
    monkeypatch.setattr(_workflow.logger, "warning", warning)
    return warnings


@pytest.mark.parametrize(("document", "fmt", "loader"), DOCUMENTS)
def test_get_document_format(document, fmt, loader):
    """Each readable document shape is recognized from its own structure."""
    assert get_document_format(document) is fmt


@pytest.mark.parametrize(("document", "fmt", "loader"), DOCUMENTS)
def test_normalize_document_matches_loader(document, fmt, loader):
    """Normalizing a document, detected or declared, yields what its loader yields."""
    expected = loader(document)
    assert normalize_document(document) == expected
    assert normalize_document(document, fmt) == expected


def test_get_document_format_rejects_unknown_shape():
    with pytest.raises(InvalidPipelineError, match="'nodes' or 'modules'"):
        get_document_format({"pipeline": []})


@pytest.mark.parametrize(
    ("document", "fmt"),
    [
        pytest.param(DAG, DocumentFormat.V2, id="dag-as-v2"),
        pytest.param(DAG, DocumentFormat.V1, id="dag-as-v1"),
        pytest.param(PIPE_DEF, DocumentFormat.DAG, id="v1-as-dag"),
        pytest.param(PIPE_DEF, DocumentFormat.V2, id="v1-as-v2"),
        pytest.param(RAW_WORKFLOW, DocumentFormat.DAG, id="v2-as-dag"),
        pytest.param(RAW_WORKFLOW, DocumentFormat.V1, id="v2-as-v1"),
    ],
)
def test_normalize_document_honors_the_declared_format(document, fmt):
    """A document read as a shape it is not written in is rejected, not guessed."""
    with pytest.raises(InvalidPipelineError):
        normalize_document(document, fmt)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        pytest.param({"modules": []}, "no nodes", id="empty-dag"),
        pytest.param({"modules": None}, "must be a list", id="null-modules"),
        pytest.param(
            {"modules": [{"type": "forever"}], "wires": 5},
            "must be a list",
            id="scalar-wires",
        ),
    ],
)
def test_invalid_pipe_dags_are_rejected_not_crashed(document, message):
    assert get_document_format(document) is DocumentFormat.DAG

    with pytest.raises(InvalidPipelineError, match=message):
        normalize_document(document)


def test_null_wires_chain_in_listing_order():
    document = {"modules": DAG["modules"], "wires": None}
    assert normalize_document(document) == parse_dag(DAG)


@pytest.mark.parametrize("document", LEGACY)
def test_require_workflow_points_at_the_converter(document):
    with pytest.raises(InvalidPipelineError, match="build-workflow"):
        require_workflow(document)


def test_require_workflow_accepts_a_workflow_document():
    assert require_workflow(WORKFLOW) == parse_dag(DAG)


def test_read_document_reports_a_missing_path(monkeypatch):
    warnings = _record_warnings(monkeypatch)
    assert read_document("no-such-flow.json") == (None, "no-such-flow")
    assert any("Unable to read input file" in warning for warning in warnings)


def test_read_document_reports_malformed_json(tmp_path, monkeypatch):
    warnings = _record_warnings(monkeypatch)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{bad json", encoding="utf-8")
    assert read_document(str(malformed)) == (None, "malformed")
    assert any("Unable to parse input" in warning for warning in warnings)


def test_read_document_reports_malformed_stdin(monkeypatch):
    warnings = _record_warnings(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("{bad json"))
    assert read_document("-") == (None, "anonymous")
    assert any("Unable to parse input" in warning for warning in warnings)


def test_read_document_parses_a_committed_document():
    document, name = read_document(str(DAG_PATH))
    assert (document, name) == (DAG, "pipe_forever")
