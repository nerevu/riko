"""
Captures every example's output into one snapshot and compares it with an earlier one.

Purpose: prove an `examples/` edit behavior-neutral. Each example module's
``pipe(test=True)``, ``async_pipe(test=True)``, and ``main(test=True)`` output, the
standalone script runs, and the stderr and riko log lines each one emits land in one
text file, so a changed item, print, or warning shows up as a diff.

Inputs: a snapshot PATH. Without ``--compare`` the current output is written there;
with ``--compare`` PATH is read as the earlier snapshot and nothing is written.

Outputs: the snapshot file (one ``=== <name> <kind>`` section per capture; an example
that raises records ``!! <ExceptionType>: <message>``), or, in compare mode, a unified
diff of the first differing section; exit 1 when any section differs. Log-line
timestamps, ANSI colors, object ids (``at 0x...``), and the repo path are normalized
away so a rerun is byte-identical; timestamps in the data itself are kept.

Origin: 2026-11-24 examples standardization, which proved byte-identical output with
a draft that missed the ``USD/ rate not found`` warning on stderr.

Run:

    python .claude/skills/tidy/snapshot_examples.py /tmp/before.txt
    python .claude/skills/tidy/snapshot_examples.py --compare /tmp/before.txt
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import logging
import re
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from pprint import pformat
from typing import TYPE_CHECKING, Any

from riko import run
from riko.base._logging import going

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from types import ModuleType

_SECTION = "=== "
_NORMALIZERS = (
    (re.compile(r"\x1b\[[0-9;]*m"), ""),
    (re.compile(r"(\[[A-Z]+) \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]"), r"\1 <TIME>]"),
    (re.compile(r" at 0x[0-9a-fA-F]+"), " at 0x.."),
)


def _run_sync(module: ModuleType) -> list[Any]:
    """Gets an example's sync items."""
    return list(module.pipe(test=True))


def _run_async(module: ModuleType) -> list[Any]:
    """Gets an example's async items."""

    async def collect() -> list[Any]:
        return [item async for item in module.async_pipe(test=True)]

    return run(collect)


def _run_main(module: ModuleType) -> str:
    """Gets nothing: an example's ``main`` prints its output instead."""
    module.main(test=True)
    return ""


_RUNNERS: tuple[tuple[str, str, Callable[[ModuleType], Any]], ...] = (
    ("sync", "pipe", _run_sync),
    ("async", "async_pipe", _run_async),
    ("main", "main", _run_main),
)
DESCRIPTION = "Snapshot every example's output, or compare it with a snapshot."
NAMES = tuple(
    f"examples.{name}"
    for name in (
        "simple1",
        "simple2",
        "gigs",
        "split",
        "demo",
        "wired",
        "kazeeki",
        "usage",
    )
)
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ("register_alias", "register_module", "usage")

sys.path.insert(0, str(ROOT))


def normalize(text: str) -> str:
    """Normalizes log timestamps, ANSI colors, object ids, and the repo path."""
    for pattern, replacement in _NORMALIZERS:
        text = pattern.sub(replacement, text)

    return text.replace(str(ROOT), "<ROOT>")


def _get_log_handlers() -> list[logging.StreamHandler[Any]]:
    """Gets riko's stream log handlers, the templates new loggers copy included."""
    loggers = [
        logger
        for name, logger in logging.root.manager.loggerDict.items()
        if name.startswith("riko") and isinstance(logger, logging.Logger)
    ]
    handlers = [*going.handlers.values()]
    handlers += [handler for logger in loggers for handler in logger.handlers]
    return [
        handler for handler in handlers if isinstance(handler, logging.StreamHandler)
    ]


@contextlib.contextmanager
def _capturing() -> Generator[io.StringIO]:
    """Yields a buffer that receives stdout, stderr, and riko log lines."""
    buf = io.StringIO()
    original = going.handlers["high"].stream
    streams = {handler: handler.setStream(buf) for handler in _get_log_handlers()}

    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield buf
    finally:
        for handler in _get_log_handlers():
            if handler.stream is buf:
                handler.setStream(streams.get(handler) or original)


def _build_section(
    header: str, func: Callable[[ModuleType], Any], module: ModuleType
) -> str:
    """Builds one section from a call's printed result and its captured output."""
    with _capturing() as buf:
        try:
            result = func(module)
        except Exception as err:  # noqa: BLE001
            result = f"!! {type(err).__name__}: {err}"

    body = result if isinstance(result, str) else pformat(result)
    return f"{_SECTION}{header}\n{buf.getvalue()}{body}"


def _gen_sections() -> Iterator[str]:
    """Yields each example's sections, then each script's."""
    for name in NAMES:
        module = import_module(name)
        short = name.rpartition(".")[2]

        for kind, attr, func in _RUNNERS:
            if hasattr(module, attr):
                yield _build_section(f"{short} {kind}", func, module)

    for script in SCRIPTS:
        proc = subprocess.run(
            [sys.executable, f"examples/{script}.py"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        yield (
            f"{_SECTION}{script} script rc={proc.returncode}\n"
            f"{proc.stdout}--- stderr\n{proc.stderr}"
        )


def capture() -> str:
    """Gets the normalized snapshot text of every example and script."""
    return normalize("\n".join(_gen_sections()))


def _split_sections(text: str) -> list[str]:
    """Gets a snapshot's sections, each starting with its header line."""
    return re.split(rf"(?m)^(?={_SECTION})", text)


def compare(before: str, after: str) -> str:
    """Gets a unified diff of the first section that differs, or ``""``."""
    pairs = zip(
        _split_sections(before) + [""], _split_sections(after) + [""], strict=False
    )
    first = next(((old, new) for old, new in pairs if old != new), ("", ""))
    diff = difflib.unified_diff(
        first[0].splitlines(), first[1].splitlines(), "before", "after", lineterm=""
    )
    return "\n".join(diff)


def main(argv: list[str] | None = None) -> int:
    """Writes or compares a snapshot and returns 1 when a compared section differs."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("path", type=Path, help="the snapshot to write or compare")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="compare the current output with PATH instead of writing it",
    )
    args = parser.parse_args(argv)
    text = capture()
    diff = compare(args.path.read_text(), text) if args.compare else ""

    if args.compare:
        print(diff or "no example output changed")
    else:
        args.path.write_text(text)

    return int(bool(diff))


if __name__ == "__main__":
    sys.exit(main())
