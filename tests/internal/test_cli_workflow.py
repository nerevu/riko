# vim: sw=4:ts=4:expandtab

"""Tests the console scripts' shared front door for reading JSON inputs."""

from __future__ import annotations

import io
import json

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.cli import _workflow
from riko.cli._workflow import read_document, require_workflow
from riko.definitions._workflow import Workflow
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
WORKFLOW = json.loads(Workflow.parse(DAG).serialize())
LEGACY = [pytest.param(DAG, id="dag"), pytest.param(PIPE_DEF, id="v1")]


def _record_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warnings: list[str] = []
    warning = lambda msg, *args: warnings.append(msg % args)
    monkeypatch.setattr(_workflow.logger, "warning", warning)
    return warnings


@pytest.mark.parametrize("document", LEGACY)
def test_require_workflow_points_at_the_converter(document):
    with pytest.raises(InvalidPipelineError, match="build-workflow"):
        require_workflow(document)


def test_require_workflow_accepts_a_workflow_document():
    assert require_workflow(WORKFLOW) == Workflow.parse(DAG)


def test_require_workflow_rejects_a_non_mapping():
    with pytest.raises(InvalidPipelineError, match="must be a mapping"):
        require_workflow([])


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
