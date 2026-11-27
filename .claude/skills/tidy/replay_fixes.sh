#!/usr/bin/env bash
# Purpose: measure mistake_scan recall on past fixes. For each fix commit, export its
# parent with git archive into a fresh mktemp dir, overlay the current scanner, and scan
# the reverse diff (the pre-fix lines read as added).
# Inputs: fix commit shas. Outputs: per-fix lead count and the first leads (RM901
# dropped); a 0-lead fix gets its `mistake_scan.py --status` in parentheses, and a
# non-behavioral fix is not replayed.
# Origin: /audit of bug-class history vs the audit skills, 2026-11-19 (promoted 2026-11-19).
set -u
R=$(git rev-parse --show-toplevel); SCAN=$R/.claude/skills/tidy/mistake_scan.py
for c in "$@"; do
  head=$(git -C "$R" log -1 --format='%h %s' "$c")
  status=$(python "$SCAN" --status "$(git -C "$R" rev-parse "$c")"); status=${status#* }
  if [ "$status" = non-behavioral ]; then
    echo "== $head :: not replayed (non-behavioral)"; continue
  fi
  d=$(mktemp -d); git -C "$R" archive "$c^" | tar -x -C "$d"
  mkdir -p "$d/.claude/skills/tidy"; cp "$SCAN" "$d/.claude/skills/tidy/"
  git -C "$R" diff "$c" "$c^" -- riko > "$d/rev.diff"
  out=$(cd "$d" && python .claude/skills/tidy/mistake_scan.py --diff-file rev.diff 2>&1 | grep -E '^riko/' | grep -v RM901)
  n=$(printf '%s' "$out" | grep -c . )
  if [ "$n" -eq 0 ]; then
    echo "== $head :: 0 leads ($status)"
  else
    echo "== $head :: $n leads"
  fi
  printf '%s\n' "$out" | head -4
done
