# vim: sw=4:ts=4:expandtab
"""Regenerates committed Python pipeline fixtures from JSON definitions."""

from __future__ import annotations

from json import loads
from typing import TYPE_CHECKING

from riko.base._config import PIPELINE_DIRS
from riko.runtime._compile import compile_pipe

if TYPE_CHECKING:
    from pathlib import Path


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
