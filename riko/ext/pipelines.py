# vim: sw=4:ts=4:expandtab
"""
riko.ext.pipelines
~~~~~~~~~~~~~~~~~~~
Resolution of *named pipelines* (``pipe_*``) — the counterpart to the
module registry. Where the registry resolves leaf module implementations, this
resolves whole sub-pipelines: a generated Python module (imported from a
configured package) or, failing that, a JSON definition compiled from a
configured directory.

The locations are **injected**, not hardcoded: core ships an empty
``pipeline_resolver`` (a bare install has no named pipelines), and the test suite
configures it with its ``tests.pypipelines`` package / ``tests/pipelines``
directory via ``conftest``. This is what removes the ``tests.*`` paths from the
core compiler.
"""

from importlib import import_module
from json import loads
from pathlib import Path
from types import ModuleType

from riko.exceptions import UnsupportedPipelineError
from riko.types.compile import ParsedPipeDef


class PipelineResolver:
    def __init__(
        self, *, package: str | None = None, directory: Path | None = None
    ) -> None:
        self._package = package
        self._directory = directory

    def _import(self, module_name: str) -> ModuleType:
        if self._package is None:
            raise ModuleNotFoundError(
                f"no pipeline package configured for {module_name!r}", name=module_name
            )

        return import_module(f"{self._package}.{module_name}")

    def _compile_from_json(
        self, pipe_name: str, file_path: Path | None
    ) -> ParsedPipeDef:
        from riko.compile import parse_pipe_def  # noqa: PLC0415

        if (directory := file_path or self._directory) is None:
            raise UnsupportedPipelineError(pipe_name)

        pipe_file = directory / f"{pipe_name}.json"

        try:
            pipe_def = loads(pipe_file.read_text())
        except OSError as e:
            raise UnsupportedPipelineError(pipe_name) from e

        return parse_pipe_def(pipe_def, pipe_name)

    def configure(
        self, *, package: str | None = None, directory: Path | None = None
    ) -> None:
        self._package = package
        self._directory = directory

    def load(
        self,
        module_name: str,
        pipe_name: str,
        *,
        compile_missing: bool = False,
        file_path: Path | None = None,
    ) -> tuple[ModuleType | None, ParsedPipeDef | None]:
        module: ModuleType | None = None
        parsed: ParsedPipeDef | None = None

        try:
            module = self._import(module_name)
        except ModuleNotFoundError as e:
            if compile_missing:
                parsed = self._compile_from_json(pipe_name, file_path)
            else:
                raise UnsupportedPipelineError(pipe_name) from e

        return module, parsed


pipeline_resolver: PipelineResolver = PipelineResolver()
