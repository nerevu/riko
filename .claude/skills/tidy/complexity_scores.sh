#!/bin/bash
# Purpose: print the McCabe complexity of every function in the given files, so an
#   inline or refactor can be checked against the C90 limit (10) before it lands.
# Inputs: Python file paths (e.g. `$(git ls-files 'riko/*.py')`).
# Outputs: one `path:line name N` line per function on stdout.
# Origin: 2026-11-22, written by the helper-chain implementers (single-use helper
#   refactor); ~0.1 s for riko/cli, 30 functions at 9+ tree-wide on that date.
cd "$(git rev-parse --show-toplevel)" || exit 1
uv run --active ruff check --select C901 --config 'lint.mccabe.max-complexity=0' \
    --output-format concise "$@" 2>&1 |
    sed -nE 's/^([^:]+):([0-9]+):[0-9]+: .*`([^`]+)` is too complex \(([0-9]+).*/\1:\2 \3 \4/p'
