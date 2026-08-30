# vim: sw=4:ts=4:expandtab
"""
Drift guard for the compiled example pipes.

Each ``examples/pypipelines/pipe_*.py`` is generated from its sibling
``examples/pipelines/pipe_*.json`` by ``compile-pipe`` (see
``_docs/COMPILING_EXAMPLE_PIPES.md``). This regenerates the module in memory and
fails if it diverges from the committed file, exactly like the
``tests/pypipelines`` guard in ``test_compile.py``. Regenerate with::

    gen-pipelines  # or: compile-pipe examples/pipelines/pipe_<name>.json -o examples/pypipelines/pipe_<name>.py
"""

from difflib import unified_diff
from json import loads

import pytest

from riko.compile import compile_pipe
from riko.paths import ROOT_DIR

PIPELINE_DIR = ROOT_DIR / "examples" / "pipelines"
PYPIPELINE_DIR = ROOT_DIR / "examples" / "pypipelines"


def _example_pipe_defs():
    return sorted(PIPELINE_DIR.glob("pipe_*.json"))


@pytest.mark.parametrize("json_path", _example_pipe_defs(), ids=lambda path: path.stem)
def test_example_pipe_matches_json(json_path):
    pipe_def = loads(json_path.read_text())
    expected = (PYPIPELINE_DIR / f"{json_path.stem}.py").read_text()
    source = compile_pipe(pipe_def, json_path.stem)
    args = (expected.splitlines(keepends=True), source.splitlines(keepends=True))
    diff = "".join(unified_diff(*args, "expected", "got"))
    assert not diff, f"{json_path.stem}.py drifted from its JSON:\n{diff}"
