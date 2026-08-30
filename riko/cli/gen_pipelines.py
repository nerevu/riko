# vim: sw=4:ts=4:expandtab
"""
riko.cli.gen_pipelines
~~~~~~~~~~~~~~~~~~~~~~~

Regenerates the compiled pipe modules from their JSON pipe definitions, the same
way ``compile-pipe`` does one file at a time. Each ``<root>/pipelines/pipe_*.json``
that has a committed ``<root>/pypipelines/pipe_*.py`` is recompiled in place, for
both the test fixtures (``tests/``) and the runnable examples (``examples/``).

Edit the JSON (not the generated module), then regenerate with ``gen-pipelines``.
``tests/internal/test_compile.py`` and ``tests/internal/test_example_pipes.py``
fail if the two layers drift.
"""

from json import loads
from pathlib import Path

from riko.compile import compile_pipe
from riko.paths import ROOT_DIR

PIPELINE_DIRS = (
    (ROOT_DIR / "tests" / "pipelines", ROOT_DIR / "tests" / "pypipelines"),
    (ROOT_DIR / "examples" / "pipelines", ROOT_DIR / "examples" / "pypipelines"),
)


def _targets() -> list[tuple[Path, Path]]:
    return [
        (src, pypipeline_dir / f"{src.stem}.py")
        for pipeline_dir, pypipeline_dir in PIPELINE_DIRS
        for src in sorted(pipeline_dir.glob("pipe_*.json"))
        if (pypipeline_dir / f"{src.stem}.py").exists()
    ]


def regenerate() -> list[Path]:
    """Recompile every JSON pipe definition that has a committed module."""
    targets = _targets()

    for src, out_path in targets:
        out_path.write_text(compile_pipe(loads(src.read_text()), src.stem))

    return [out_path for _, out_path in targets]


def main() -> int:
    """Regenerate the compiled pipe modules from their JSON definitions."""
    return 0 if regenerate() else 1


if __name__ == "__main__":
    raise SystemExit(main())
