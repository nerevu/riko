"""
List the wording changes in Markdown files, ignoring line reflow and markup.

Purpose: a `rumdl fmt` reflow rewrites thousands of lines without changing a word, which
buries the real edits in a diff. This compares each changed Markdown file's words
against a base ref, after dropping markup tokens (table pipes, list markers, heading
hashes, emphasis), and prints only the wording that changed.

Inputs: BASE (a git ref, default HEAD) and optional path prefixes to skip.

Outputs: one `== path (N changes)` block per file with word-level changes, each change
as `[tag] ...context | -old +new`; nothing for a file whose words are unchanged.

Origin: 2026-11-05 /land tidy run over the repo-wide rumdl reflow (cut a 2.2 MB diff to
about 7 kB of real edits); the session also ran the same comparison by hand four times.
"""

import difflib
import re
import shutil
import subprocess
import sys

GIT = shutil.which("git") or "git"
_MARKUP = re.compile(r"^(?:[|\-*+#>=]+|\d+[.)]|[*_]{1,3})$")


def _words(text: str) -> list[str]:
    return [word.strip("*_") for word in text.split() if not _MARKUP.match(word)]


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    skip = tuple(sys.argv[2:])
    args = [GIT, "diff", "--name-only", base, "--", "*.md"]
    files = subprocess.check_output(args, text=True).split()

    for path in files:
        if skip and path.startswith(skip):
            continue

        try:
            old = subprocess.check_output([GIT, "show", f"{base}:{path}"], text=True)
        except subprocess.CalledProcessError:
            old = ""

        with open(path, encoding="utf-8") as f:
            a, b = _words(old), _words(f.read())

        matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
        changes = [
            f"  [{tag}] ...{' '.join(b[max(0, j1 - 6) : j1])} | "
            f"-{' '.join(a[i1:i2])[:300]!r} +{' '.join(b[j1:j2])[:300]!r}"
            for tag, i1, i2, j1, j2 in matcher.get_opcodes()
            if tag != "equal"
        ]

        if changes:
            print(f"== {path} ({len(changes)} changes)")
            print("\n".join(changes[:40]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
