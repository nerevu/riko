"""
Reveals pyright's inferred type for named riko symbols or expressions.

Usage:
    python .claude/skills/tidy/reveal_types.py MODULE:EXPR [MODULE:EXPR ...]
    python .claude/skills/tidy/reveal_types.py riko.definitions._normalize:require_edge
    python .claude/skills/tidy/reveal_types.py \\
        "riko.base._require_guards:require_from_keys({'x'}, {'y'})"

Answers "what does pyright think X is?" without hand-writing a ``reveal_type``
scratch file (an ``Unknown`` leak, an overload pick, a guard's narrowed type).
EXPR starts with a name importable from MODULE; that leading name is imported
under a private alias and the whole expression is revealed.

Output is one ``MODULE:EXPR -> type`` line per argument, in argument order; an
argument pyright revealed nothing for prints ``(not revealed)``, and one that is not
``MODULE:EXPR`` Python syntax prints ``(syntax error)`` and is left out of the probe,
so it cannot swallow the arguments after it. Each pyright error goes to stderr as
``MODULE:EXPR: message``. Exits 1 on a syntax error or a pyright error and 2 when
pyright gives no JSON report.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_NAME_RE = re.compile(r"\w+")
_TYPE_RE = re.compile(r'Type of ".*" is "(?P<type>.*)"')
COMMAND = ("uv", "run", "--active", "--no-sync", "pyright", "--outputjson")
NOT_REVEALED = "(not revealed)"
SYNTAX_ERROR = "(syntax error)"


def is_valid(spec: str) -> bool:
    module, sep, expr = spec.partition(":")

    try:
        ast.parse(module.strip(), mode="eval")
        ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        valid = False
    else:
        valid = bool(sep)

    return valid


def get_probe_lines(n: int, spec: str) -> tuple[str, str]:
    module, expr = (part.strip() for part in spec.split(":", 1))
    match = _NAME_RE.match(expr)
    name = "" if match is None else match.group()
    alias = f"_s{n}"
    tail = expr[len(name) :]
    return f"from {module} import {name} as {alias}", f"reveal_type({alias}{tail})"


def load_report(*valid: str) -> dict | None:
    probe = ["from typing import reveal_type"]

    for n, spec in enumerate(valid):
        probe.extend(get_probe_lines(n, spec))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "reveal.py")
        path.write_text("\n".join(probe) + "\n")
        cmd = [*COMMAND, str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"pyright gave no JSON report:\n{result.stderr}", file=sys.stderr)
        report = None

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("specs", nargs="+", metavar="MODULE:EXPR")
    specs: list[str] = parser.parse_args(argv).specs
    valid = [spec for spec in specs if is_valid(spec)]
    report = load_report(*valid) if valid else {"generalDiagnostics": []}

    if report is None:
        status = 2
    else:
        diagnostics = report["generalDiagnostics"]
        revealed = {
            valid[(d["range"]["start"]["line"] - 1) // 2]: m.group("type")
            for d in diagnostics
            if d["severity"] == "information" and (m := _TYPE_RE.match(d["message"]))
        }
        errors = [
            (valid[max(d["range"]["start"]["line"] - 1, 0) // 2], d["message"])
            for d in diagnostics
            if d["severity"] == "error"
        ]

        for spec in specs:
            type_ = revealed.get(spec, NOT_REVEALED) if spec in valid else SYNTAX_ERROR
            print(f"{spec} -> {type_}")

        for spec, message in errors:
            print(f"{spec}: {message}", file=sys.stderr)

        status = 1 if errors or len(valid) < len(specs) else 0

    return status


if __name__ == "__main__":
    sys.exit(main())
