"""
Repoints doc citations of commits a rebase or autosquash rewrote.

Purpose: after a rebase, a doc that cites a rewritten commit names a sha HEAD no
longer reaches. Claude repoints those citations itself, as a skill step, so the user
never does.
Inputs: tracked text files under ``_docs/``, ``docs/``, ``CLAUDE.md``,
``CONTRIBUTING.rst``, ``README.rst``, and ``.claude/skills/``, plus every file under
``--paths`` (default: the memory directory ``memory_audit.py`` audits; a bare
``--paths`` scans none). Both skip any ``disposed/``, ``drafts/``, or
``memory-archive/`` directory and ``_docs/archive/`` (history), and
``mistake_scan.py``, whose refs ``--remap`` owns. A hex token of 7-40 characters is
stale when it names a commit HEAD does not reach. Its successor is the first of:

- ``subject``: the one commit since the stale commit forked from HEAD with its
  subject, as ``mistake_scan.py``'s ``resolve_successor`` finds it;
- ``fixup``/``amend``: for a ``fixup!``/``amend!`` commit, the same match on its
  target's subject (or its target sha's successor), and for ``amend!`` on the
  amended subject too, the body's first non-empty line;
- ``history``: the one commit with that subject anywhere in HEAD's history;
- ``content``: the commit HEAD reaches that first added the stale commit's two
  longest added lines (25+ characters), when both lines agree on it. Code lines
  come first; prose (``*.md``, ``*.rst``, ``*.txt``, ``docs/``, ``_docs/``, and
  string, docstring, or comment lines in code, found with ``tokenize`` for ``.py``,
  and import lines) counts only when the commit adds no code line, since folds
  reword prose.

An example in a docstring cites a token that is no commit id, never a real hash, so
it never goes stale.
Outputs: one ``path:line old → new (method)`` per repointed token, written in place
unless ``--dry-run``; then one ``path:line sha: kept (mapping record)`` per stale token
a line deliberately records as the old side of a mapping (``old → new`` or
``old -> new``, short words or backticks between), which never changes the exit code;
then one ``path:line sha: no fallback resolves it`` per token left alone. Without
``--dry-run`` it then runs ``mistake_scan.py --remap`` for ``CLASS_HISTORY`` and prints
its exit code; ``--remap`` exits 1 for pending ``uncommitted`` refs, which is normal,
so that code never becomes this script's. Exits 1 only when a stale token is left
unresolved.
Origin: user ruling 2026-11-25 ("you should always repoint hashes. not me."), run by
/land step 1 and /wrapup step 1.

Run:

    python .claude/skills/wrapup/repoint_hashes.py
    python .claude/skills/wrapup/repoint_hashes.py --dry-run
    python .claude/skills/wrapup/repoint_hashes.py --paths  # repo docs only

Smoke tests:

    uv run --active pytest .claude/skills/wrapup/test_repoint_hashes.py --no-cov
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import TYPE_CHECKING

from memory_audit import DEFAULT_MEMORY

if TYPE_CHECKING:
    from collections.abc import Iterator

_HEX = r"(?<![0-9A-Za-z_])[0-9a-f]{7,40}(?![0-9A-Za-z_])"
_MIN_LINE = 25
_PROSE_DIRS = ("docs/", "_docs/")
_PROSE_SUFFIXES = (".md", ".rst", ".txt")
GIT = shutil.which("git") or "git"
HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)")
IMPORT_RE = re.compile(r"import |from \S+ import ")
MAPPING_RE = re.compile(rf"{_HEX}(?=[^→\n]{{0,20}}?(?:→|->)[^\n]{{0,20}}?{_HEX})")
REMAP_SCRIPT = Path(".claude/skills/tidy/mistake_scan.py")
ROOTS = (
    "_docs",
    "docs",
    "CLAUDE.md",
    "CONTRIBUTING.rst",
    "README.rst",
    ".claude/skills",
)
SKIPPED = ("_docs/archive/", str(REMAP_SCRIPT))
SKIPPED_DIRS = {"disposed", "drafts", "memory-archive"}
SQUASH_PREFIXES = ("fixup! ", "amend! ")
TOKEN_RE = re.compile(_HEX)


def git(*args: str, check: bool = True, stdin: str | None = None) -> str:
    return subprocess.run(
        [GIT, *args], capture_output=True, text=True, check=check, input=stdin
    ).stdout


def is_skipped(relative: str) -> bool:
    return relative.startswith(SKIPPED) or bool(
        SKIPPED_DIRS & set(Path(relative).parts)
    )


def load_files(root: Path, extra: list[Path]) -> list[Path]:
    """Loads the tracked doc files under the default roots plus every extra file."""
    listed = git("ls-files", "-z", "--", *ROOTS).split("\0")
    tracked = [root / rel for rel in listed if rel and not is_skipped(rel)]
    extras = [
        path
        for base in extra
        for path in ([base] if base.is_file() else sorted(base.rglob("*")))
        if path.is_file() and not is_skipped(path.relative_to(base).as_posix())
    ]
    return [*tracked, *extras]


def read_texts(files: list[Path]) -> dict[Path, str]:
    texts: dict[Path, str] = {}

    for path in files:
        try:
            texts[path] = path.read_text()
        except (UnicodeDecodeError, OSError):
            pass

    return texts


def resolve_commits(tokens: set[str]) -> dict[str, str]:
    """Resolves each token naming a commit to its full sha."""
    ordered = sorted(tokens)
    stdin = "".join(f"{token}^{{commit}}\n" for token in ordered)
    rows = git("cat-file", "--batch-check", stdin=stdin).splitlines()
    return {
        token: row.split()[0]
        for token, row in zip(ordered, rows, strict=True)
        if row.split()[1:2] == ["commit"]
    }


def is_reachable(sha: str) -> bool:
    cmd = [GIT, "merge-base", "--is-ancestor", sha, "HEAD"]
    return subprocess.run(cmd, capture_output=True, check=False).returncode == 0


def match_subject(subjects: list[str], revisions: str) -> str | None:
    """
    Matches the one commit in ``revisions`` carrying the first subject any commit has.

    Tries ``subjects`` in order; ``None`` when that subject has two or more commits.
    """
    log = git("log", "--format=%H %s", revisions).splitlines()
    counts = [
        [line[:40] for line in log if line[41:] == subject] for subject in subjects
    ]
    found = next((matches for matches in counts if matches), [])
    return found[0] if len(found) == 1 else None


def is_prose(path: str) -> bool:
    return path.endswith(_PROSE_SUFFIXES) or path.startswith(_PROSE_DIRS)


def load_python_prose(sha: str, path: str) -> set[int]:
    """
    Loads the line numbers of ``path`` at ``sha`` that hold a string or comment token.

    A multi-line string (a docstring) marks every line it spans. A file ``tokenize``
    rejects marks none, so its lines count as code.
    """
    source = git("show", f"{sha}:{path}", check=False)

    try:
        lines = {
            number
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type in {tokenize.STRING, tokenize.COMMENT}
            for number in range(token.start[0], token.end[0] + 1)
        }
    except (tokenize.TokenError, SyntaxError):
        lines = set()

    return lines


def gen_added(sha: str) -> Iterator[tuple[str, int, str]]:
    """Generates each ``(path, new line number, stripped text)`` that ``sha`` adds."""
    patch = git("show", "--format=", "--no-color", "--no-ext-diff", "-U0", sha)
    path = ""
    number = 0

    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = line.removeprefix("+++ ").removeprefix("b/")
        elif match := HUNK_RE.match(line):
            number = int(match.group(1))
        elif line.startswith("+"):
            yield path, number, line[1:].strip()
            number += 1


def load_added_lines(sha: str) -> list[str]:
    """
    Loads the two longest distinct lines ``sha`` adds that are specific enough.

    Code lines come first: folds and rewords merge changelog, doc, docstring, and
    comment prose into older wording, while code carries over intact. Prose lines count
    only when ``sha`` adds no qualifying code line. Prose is a whole doc file, a line of
    a ``.py`` file inside a string or comment token (the file read at ``sha``), a
    ``#`` line of any other code file, or an import line, generic boilerplate that
    commits keep adding and removing.
    """
    added: dict[bool, set[str]] = {True: set(), False: set()}
    python: dict[str, set[int]] = {}

    for path, number, text in gen_added(sha):
        if path.endswith(".py") and path not in python:
            python[path] = load_python_prose(sha, path)

        prose = (
            is_prose(path)
            or number in python.get(path, set())
            or (not path.endswith(".py") and text.startswith("#"))
            or bool(IMPORT_RE.match(text))
        )

        if len(text) >= _MIN_LINE:
            added[prose].add(text)

    return sorted(added[False] or added[True], key=len)[-2:]


def match_content(sha: str) -> str | None:
    """
    Matches the commit HEAD reaches that introduced ``sha``'s two longest added lines.

    Each line's oldest introducing commit (``git log -S``) must be the same one.
    """
    lines = load_added_lines(sha)
    oldest = {
        (git("log", "--format=%H", f"-S{line}", "HEAD").split() or [""])[-1]
        for line in lines
    }
    found = oldest.pop() if len(lines) == 2 and len(oldest) == 1 else ""
    return found or None


def load_subjects(sha: str) -> tuple[str, list[str]]:
    """Loads the method label and the subjects a successor of ``sha`` may carry."""
    subject = git("log", "-1", "--format=%s", sha, check=False).strip()
    body = git("log", "-1", "--format=%b", sha, check=False).splitlines()
    target = subject
    method = "subject"

    while target.startswith(SQUASH_PREFIXES):
        method = "amend" if target.startswith("amend! ") else "fixup"
        target = target.split(" ", 1)[1]

    amended = next((line.strip() for line in body if line.strip()), "")
    extra = [amended] if method == "amend" and amended else []
    return method, [target, *extra] if target else extra


def resolve_successor(sha: str) -> tuple[str, str] | None:
    """
    Resolves a full sha HEAD no longer reaches to its rewritten full sha and method.

    Tries, in order: the one commit since ``sha`` forked from HEAD with its subject
    (as ``mistake_scan.py``'s ``resolve_successor`` does), where a ``fixup!`` or
    ``amend!`` commit uses its target's subject (or its target sha's successor) and an
    ``amend!`` commit also its amended subject, the body's first line; then the one
    commit with that subject anywhere in HEAD's history; then the commit that
    introduced ``sha``'s two longest added lines.
    """
    method, subjects = load_subjects(sha)
    target = subjects[0] if subjects else ""
    named = (
        resolve_commits({target}).get(target) if TOKEN_RE.fullmatch(target) else None
    )
    base = git("merge-base", sha, "HEAD", check=False).strip()

    if named is not None and named != sha:
        chained = (named, method) if is_reachable(named) else resolve_successor(named)
        found = (chained[0], method) if chained else None
    elif base and (forked := match_subject(subjects, f"{base}..HEAD")):
        found = (forked, method)
    elif history := match_subject(subjects, "HEAD"):
        found = (history, "history")
    elif content := match_content(sha):
        found = (content, "content")
    else:
        found = None

    return found


def repoint_line(
    line: str, renames: dict[str, tuple[str, str]]
) -> tuple[str, list[tuple[str, bool]]]:
    """
    Repoints each renamed token in ``line``, leaving a mapping record's old side.

    Returns the new line and each token with whether a mapping record keeps it.
    """
    kept = {match.start() for match in MAPPING_RE.finditer(line)}
    pieces: list[str] = []
    tokens: list[tuple[str, bool]] = []
    end = 0

    for match in TOKEN_RE.finditer(line):
        token = match.group()
        is_kept = match.start() in kept
        new = renames[token][0] if token in renames and not is_kept else token
        pieces += [line[end : match.start()], new]
        tokens.append((token, is_kept))
        end = match.end()

    return "".join([*pieces, line[end:]]), tokens


def repoint(
    texts: dict[Path, str], root: Path, dry_run: bool
) -> tuple[list[str], list[str], list[str]]:
    """
    Repoints each stale token in ``texts``, writing the files unless ``dry_run``.

    Returns the repointed, kept (a mapping record's old side), and unresolved lines.
    """
    tokens = {token for text in texts.values() for token in TOKEN_RE.findall(text)}
    commits = resolve_commits(tokens) if tokens else {}
    reachable = set(git("rev-list", "HEAD").split())
    stale = {sha for sha in commits.values() if sha not in reachable}
    successors = {sha: resolve_successor(sha) for sha in sorted(stale)}
    renames = {
        token: (found[0][: len(token)], found[1])
        for token, sha in commits.items()
        if (found := successors.get(sha))
    }
    left = {token for token, sha in commits.items() if sha in stale} - set(renames)
    moved: list[str] = []
    kept: list[str] = []
    unresolved: list[str] = []

    for path, text in texts.items():
        shown = path.relative_to(root) if path.is_relative_to(root) else path
        lines = text.splitlines(keepends=True)

        for number, line in enumerate(lines, 1):
            lines[number - 1], found = repoint_line(line, renames)

            for token, is_kept in found:
                where = f"{shown}:{number} {token}"

                if is_kept and (token in renames or token in left):
                    kept.append(f"{where}: kept (mapping record)")
                elif token in renames:
                    new, method = renames[token]
                    moved.append(f"{where} → {new} ({method})")
                elif token in left:
                    unresolved.append(f"{where}: no fallback resolves it")

        new_text = "".join(lines)

        if new_text != text and not dry_run:
            path.write_text(new_text)

    return moved, kept, unresolved


def run_remap(root: Path, dry_run: bool) -> int:
    script = root / REMAP_SCRIPT

    if not script.exists():
        result = 0
    elif dry_run:
        print(f"would run: python {REMAP_SCRIPT} --remap")
        result = 0
    else:
        result = subprocess.run(
            [sys.executable, str(script), "--remap"], check=False
        ).returncode
        print(f"mistake_scan.py --remap exited {result}")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--paths", nargs="*", type=Path, default=[DEFAULT_MEMORY])
    args = parser.parse_args(argv)
    root = Path(git("rev-parse", "--show-toplevel").strip())
    extra = [path.expanduser().resolve() for path in args.paths]
    texts = read_texts(load_files(root, extra))
    moved, kept, unresolved = repoint(texts, root, args.dry_run)

    for line in [*moved, *kept, *unresolved]:
        print(line)

    run_remap(root, args.dry_run)
    return int(bool(unresolved))


if __name__ == "__main__":
    sys.exit(main())
