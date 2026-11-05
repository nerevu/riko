#!/usr/bin/env python3
"""
Benchmark a randomized sequence of first-parent merge commits.

By default, run the historical revision's benchmark script under uv. Alternatively,
pass a command directly, as with ``git bisect run manage test -px``:
``benchmark-commits manage test -px``. It runs through that revision's uv environment
unless explicitly invoked with uv or --raw-command. Use ``--`` only where needed
to separate options. With --benchmark-script, trailing arguments go to the script.
Each invocation runs in a detached worktree at the selected revision. Exit 125
skips a commit; other nonzero exits record a failure. Commands without recognizable
per-test benchmark output report total wall time under ``__command__``.
All merges are tested unless their count exceeds --threshold, in which case a
reproducible random subset is tested. The original checkout is left untouched.
The benchmark script owns its internal repetition settings; by default, it is
invoked only once per commit (use --runs for independent process repetitions).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import shutil
import signal
import statistics
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

import click

FIELDS = (
    "branch",
    "commit",
    "commit_date",
    "subject",
    "benchmark_blob",
    "test",
    "runs",
    "median_seconds",
    "min_seconds",
    "max_seconds",
    "status",
    "error",
)
UNITS = {"secs": 1.0, "msecs": 1e-3, "usecs": 1e-6}
RESULT = re.compile(
    r"^\s*(\w+)\s+-\s+(\d+) repetitions/loop, "
    r"best of (\d+) loops:\s+([\d.eE+-]+)\s+(secs|msecs|usecs)\s*$",
    re.MULTILINE,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def resolve_commit(repo: Path, ref: str) -> str:
    """Resolve a branch, tag, or commit identifier to a commit SHA."""
    try:
        return git(
            repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"Unknown commit/ref: {ref}") from exc


def merge_commits(
    repo: Path, *, branch: str, start: str | None, end: str | None, since: str | None
) -> list[str]:
    """
    Find branch-mainline merges in (start, end], newest first.

    Both boundaries must lie on the branch's first-parent chain. ``start`` is
    exclusive and ``end`` is inclusive (and defaults to the branch tip).
    """
    branch_sha = resolve_commit(repo, branch)
    end_sha = resolve_commit(repo, end) if end else branch_sha
    start_sha = resolve_commit(repo, start) if start else None

    branch_history = set(
        git(repo, "rev-list", "--first-parent", branch_sha).splitlines()
    )
    if end_sha not in branch_history:
        raise ValueError(
            f"End commit {end_sha[:12]} is not on {branch}'s first-parent history"
        )
    if start_sha:
        end_history = set(git(repo, "rev-list", "--first-parent", end_sha).splitlines())
        if start_sha not in end_history:
            raise ValueError(
                "Start commit must precede end commit on the first-parent history"
            )

    options = ["rev-list", "--first-parent", "--merges"]
    if since:
        options.append(f"--since={since}")
    revisions = f"{start_sha}..{end_sha}" if start_sha else end_sha
    return git(repo, *options, revisions).splitlines()


def choose_commits(
    merges: list[str], *, threshold: int, seed: int, all_commits: bool
) -> list[str]:
    """Shuffle all merges, or randomly sample threshold merges if exceeded."""
    rng = random.Random(seed)
    if not all_commits and len(merges) > threshold:
        return rng.sample(merges, k=threshold)
    chosen = list(merges)
    rng.shuffle(chosen)
    return chosen


def resolve_script(repo: Path, given: Path) -> tuple[Path, Path | None]:
    """Return (absolute path, repo-relative path or None for an external script)."""
    absolute = (repo / given).resolve()
    if absolute.suffix != ".py":
        raise ValueError("--benchmark-script must refer to a .py file")
    try:
        relative = absolute.relative_to(repo)
    except ValueError:
        if not absolute.is_file():
            raise ValueError(
                f"External benchmark script does not exist: {absolute}"
            ) from None
        return absolute, None
    return absolute, relative


def script_blob(repo: Path, sha: str, absolute: Path, relative: Path | None) -> str:
    """Identify the script revision, or indicate it is absent at this commit."""
    if relative is None:
        return git(repo, "hash-object", str(absolute))
    try:
        return git(repo, "rev-parse", "--verify", f"{sha}:{relative.as_posix()}")
    except subprocess.CalledProcessError:
        return "missing"


def script_command(worktree: Path, absolute: Path, relative: Path | None) -> list[str]:
    """Run package scripts as modules, and standalone scripts by file path."""
    if relative is None:
        return ["python", str(absolute)]

    script = worktree / relative
    if not script.is_file():
        raise FileNotFoundError(
            f"Benchmark script not present at this revision: {relative}"
        )
    parts = relative.with_suffix("").parts
    package_dirs = [worktree.joinpath(*parts[:n]) for n in range(1, len(parts))]
    if (
        len(parts) > 1
        and all((folder / "__init__.py").is_file() for folder in package_dirs)
        and all(part.isidentifier() for part in parts)
    ):
        return ["python", "-m", ".".join(parts)]
    return ["python", relative.as_posix()]


def command_in_worktree(repo: Path, worktree: Path, argv: Sequence[str]) -> list[str]:
    """
    Translate absolute paths within the repository to this checkout.

    Under ``git bisect run`` those absolute paths point to the current checkout;
    here the current checkout is deliberately a separate Git worktree.
    """
    adjusted = []
    for arg in argv:
        path = Path(arg)
        if path.is_absolute():
            try:
                arg = str(worktree / path.relative_to(repo))
            except ValueError:
                pass
        adjusted.append(arg)
    return adjusted


def command_fingerprint(repo: Path, argv: Sequence[str]) -> str:
    """
    Fingerprint an explicit command, including absolute local file arguments.

    The commit SHA already identifies tracked repo-relative scripts. Hashing
    absolute local script contents also detects changes outside the repository.
    """
    digest = hashlib.sha256()
    for arg in argv:
        digest.update(os.fsencode(arg))
        digest.update(b"\x00")
        path = Path(arg)
        if path.is_absolute() and path.is_file():
            try:
                path.relative_to(repo)
            except ValueError:
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "command:" + digest.hexdigest()[:24]


class BenchmarkSkipped(Exception):
    """A benchmark command exited 125, signaling an untestable revision."""


def parse_results(output: str) -> dict[str, float]:
    """Return seconds per call for each test printed by the benchmark script."""
    results: dict[str, float] = {}
    for name, number, _loops, duration, unit in RESULT.findall(output):
        if name in results:
            raise ValueError(f"Duplicate benchmark result: {name}")
        results[name] = float(duration) * UNITS[unit] / int(number)
    if not results:
        raise ValueError(f"No benchmark results recognized: {output[-500:]!r}")
    return results


def benchmark(
    repo: Path,
    worktree: Path,
    *,
    absolute: Path | None,
    relative: Path | None,
    command_override: list[str] | None,
    script_args: list[str],
    runs: int,
    python: str,
    timeout: int,
    extras: list[str],
    raw_command: bool,
) -> dict[str, list[float]]:
    results: dict[str, list[float]] = defaultdict(list)
    expected: set[str] | None = None
    if command_override is not None:
        command = command_in_worktree(repo, worktree, command_override)
        if not raw_command and Path(command[0]).name != "uv":
            # Like `git bisect run`, but use this checkout's console scripts and
            # dependencies rather than the caller's editable install / venv.
            uv_options = ["--locked", "--python", python]
            for extra in extras:
                uv_options.extend(["--extra", extra])
            env = {**os.environ, "PYTHONHASHSEED": "94967295", "UV_NO_PROGRESS": "1"}
            try:
                sync = subprocess.run(
                    ["uv", "sync", *uv_options],
                    cwd=worktree,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"uv sync timed out after {timeout}s") from exc
            if sync.returncode:
                raise RuntimeError(
                    f"uv sync exited {sync.returncode}: {sync.stderr[-1200:]}"
                )
            command = ["uv", "run", "--no-sync", *command]
    else:
        if absolute is None:
            raise ValueError("No benchmark script or command provided")
        command = ["uv", "run", "--locked", "--no-dev", "--python", python]
        for extra in extras:
            command.extend(["--extra", extra])
        command.extend(script_command(worktree, absolute, relative))
        command.extend(script_args)
    env = {**os.environ, "PYTHONHASHSEED": "94967295", "UV_NO_PROGRESS": "1"}

    for attempt in range(1, runs + 1):
        # Temporary files avoid deadlocks if a subprocess leaves worker children
        # holding stdout/stderr open (e.g. multiprocessing.Pool).
        with (
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file,
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file,
        ):
            started = perf_counter()
            proc = subprocess.Popen(
                command,
                cwd=worktree,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
            )
            try:
                returncode = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    proc.kill()
                proc.wait()
                raise RuntimeError(f"Run {attempt} timed out after {timeout}s") from exc
            elapsed = perf_counter() - started
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_text = stdout_file.read()
            stderr_text = stderr_file.read()

        if returncode:
            details = (stderr_text + "\n" + stdout_text).strip()
            description = f"Run {attempt} exited {returncode}: {details[-1200:]}"
            if returncode == 125:
                raise BenchmarkSkipped(description)
            raise RuntimeError(description)
        if command_override is not None and not RESULT.search(stdout_text):
            current = {"__command__": elapsed}
        else:
            current = parse_results(stdout_text)
        if expected is not None and set(current) != expected:
            raise ValueError(f"Run {attempt} returned a different set of tests")
        expected = set(current)
        for test, seconds in current.items():
            results[test].append(seconds)
    return results


def invocation_identity(
    base: str,
    *,
    script_args: list[str],
    python: str,
    extras: list[str],
    runs: int,
    command_override: bool,
    raw_command: bool,
    explicit_uv: bool,
) -> str:
    """
    Separate CSV records when benchmark arguments or runtime settings differ.

    Preserve previous identities for the default configuration so existing CSVs
    can resume without changing their columns.
    """
    settings = {"args": script_args, "runs": runs}
    defaults = {"args": [], "runs": 1}
    if not command_override:
        settings.update({"python": python, "extras": extras})
        defaults.update({"python": "3.12", "extras": ["async"]})
    elif not raw_command and not explicit_uv:
        settings.update({"python": python, "extras": extras, "uv_wrap": True})
    if settings == defaults:
        return base
    digest = hashlib.sha256(
        json.dumps(settings, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{base}:invocation:{digest}"


def existing_commits(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"CSV has incompatible columns: {path}")
        return {(row["branch"], row["commit"], row["benchmark_blob"]) for row in reader}


def error_row(common: dict[str, str], error: Exception) -> dict[str, object]:
    return {
        **common,
        "test": "__benchmark__",
        "runs": 0,
        "median_seconds": "",
        "min_seconds": "",
        "max_seconds": "",
        "status": "skipped" if isinstance(error, BenchmarkSkipped) else "error",
        "error": str(error).replace("\n", " | ")[-1200:],
    }


@click.command(
    name="benchmark-commits",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        # Options after the command belong to that command, as in git bisect run.
        "allow_interspersed_args": False,
    },
    epilog=(
        "Examples: benchmark-commits benchmark | "
        "benchmark-commits --threshold 50 benchmark | "
        "benchmark-commits manage test -px | "
        "benchmark-commits --benchmark-script riko/cli/benchmark.py -- --loops 5. "
        "The benchmark script must implement its own options."
    ),
)
@click.option(
    "--repo",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("."),
    show_default=True,
    help="Git repository directory.",
)
@click.option(
    "--branch",
    default="next",
    show_default=True,
    help="Local branch or remote-tracking ref.",
)
@click.option(
    "--benchmark-script",
    type=click.Path(path_type=Path, dir_okay=False),
    metavar="PATH",
    help="Run this Python script at each commit (repo-relative or external).",
)
@click.option(
    "--start-commit",
    "--start",
    "start_commit",
    metavar="REF",
    help="Exclusive lower bound on first-parent history.",
)
@click.option(
    "--end-commit",
    "--end",
    "end_commit",
    metavar="REF",
    help="Inclusive upper bound (defaults to branch tip).",
)
@click.option(
    "--threshold",
    "--count",
    type=click.IntRange(min=1),
    default=20,
    show_default=True,
    help="Sample this many merges only when the total exceeds it.",
)
@click.option("--all", "all_commits", is_flag=True, help="Disable sampling.")
@click.option("--since", help="Optional commit-date filter, e.g. 2026-01-01.")
@click.option(
    "--seed",
    type=int,
    default=42,
    show_default=True,
    help="Random seed for sampling and execution order.",
)
@click.option(
    "--runs",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Full benchmark invocations per commit; benchmark.py owns its own loops.",
)
@click.option(
    "--python",
    "python_version",
    default="3.12",
    show_default=True,
    help="Python version for uv.",
)
@click.option(
    "--extra",
    multiple=True,
    help="Additional uv extra; async is always enabled. May be repeated.",
)
@click.option(
    "--timeout",
    type=click.IntRange(min=1),
    default=300,
    show_default=True,
    help="Timeout in seconds per invocation, including uv sync.",
)
@click.option(
    "--raw-command",
    is_flag=True,
    help="Run the supplied command as-is, without adding uv run.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("benchmark_history.csv"),
    show_default=True,
    help="CSV output file (appended/resumed).",
)
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def main(
    repo: Path,
    branch: str,
    benchmark_script: Path | None,
    start_commit: str | None,
    end_commit: str | None,
    threshold: int,
    all_commits: bool,
    since: str | None,
    seed: int,
    runs: int,
    python_version: str,
    extra: tuple[str, ...],
    timeout: int,
    raw_command: bool,
    output: Path,
    command: tuple[str, ...],
) -> None:
    """
    Benchmark merge commits with a git-bisect-run-style COMMAND [ARGS]... .

    Runner options come before COMMAND. Anything after COMMAND is forwarded
    unchanged, including unknown options such as -px or --loops. In script mode,
    supply arguments after -- to keep them separate from runner options.
    """
    argv = list(command)
    if argv and argv[0] == "--":
        argv.pop(0)
    if benchmark_script is None:
        script_args: list[str] = []
        command_override: list[str] | None = argv or None
    else:
        script_args = argv
        command_override = None

    if raw_command and command_override is None:
        raise click.UsageError("--raw-command requires a command")

    requires_uv = (
        command_override is None
        or not raw_command
        or Path(command_override[0]).name == "uv"
    )
    if requires_uv and shutil.which("uv") is None:
        raise click.UsageError(
            "uv executable not found in PATH (use --raw-command to skip uv)"
        )

    extras = ["async", *extra]
    try:
        repo = Path(git(repo.resolve(), "rev-parse", "--show-toplevel"))
        if command_override is None:
            absolute, relative = resolve_script(
                repo, benchmark_script or Path("riko/cli/benchmark.py")
            )
        else:
            absolute, relative = None, None
        merges = merge_commits(
            repo, branch=branch, start=start_commit, end=end_commit, since=since
        )
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise click.UsageError(str(exc)) from exc

    if not merges:
        raise click.UsageError(
            "No first-parent merge commits found in the requested range"
        )
    chosen = choose_commits(
        merges, threshold=threshold, seed=seed, all_commits=all_commits
    )
    mode = "all" if len(chosen) == len(merges) else "sampled"
    click.echo(
        f"Found {len(merges)} merge commits; "
        f"testing {len(chosen)} ({mode}, randomized order)"
    )

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        finished = existing_commits(output)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    with output.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if stream.tell() == 0:
            writer.writeheader()
            stream.flush()

        for index, sha in enumerate(chosen, 1):
            date_subject = git(repo, "log", "-1", "--format=%cI%x09%s", sha)
            commit_date, subject = date_subject.split("\t", 1)
            common = {
                "branch": branch,
                "commit": sha,
                "commit_date": commit_date,
                "subject": subject,
                "benchmark_blob": "",
            }
            try:
                common["benchmark_blob"] = invocation_identity(
                    command_fingerprint(repo, command_override)
                    if command_override is not None
                    else script_blob(repo, sha, absolute, relative),
                    script_args=script_args,
                    python=python_version,
                    extras=extras,
                    runs=runs,
                    command_override=command_override is not None,
                    raw_command=raw_command,
                    explicit_uv=bool(
                        command_override is not None
                        and Path(command_override[0]).name == "uv"
                    ),
                )
                if (branch, sha, common["benchmark_blob"]) in finished:
                    click.echo(f"[{index}/{len(chosen)}] {sha[:12]}: already recorded")
                    continue
                click.echo(f"[{index}/{len(chosen)}] {sha[:12]}: {subject}")
                if common["benchmark_blob"].startswith("missing"):
                    raise BenchmarkSkipped(
                        f"Script {relative} does not exist at {sha[:12]}"
                    )
                with tempfile.TemporaryDirectory(prefix="riko-bench-") as folder:
                    worktree = Path(folder) / "checkout"
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(repo),
                            "worktree",
                            "add",
                            "--detach",
                            str(worktree),
                            sha,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    try:
                        timings = benchmark(
                            repo,
                            worktree,
                            absolute=absolute,
                            relative=relative,
                            command_override=command_override,
                            script_args=script_args,
                            runs=runs,
                            python=python_version,
                            timeout=timeout,
                            extras=extras,
                            raw_command=raw_command,
                        )
                    finally:
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(repo),
                                "worktree",
                                "remove",
                                "--force",
                                str(worktree),
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                        )

                rows = [
                    {
                        **common,
                        "test": name,
                        "runs": len(samples),
                        "median_seconds": statistics.median(samples),
                        "min_seconds": min(samples),
                        "max_seconds": max(samples),
                        "status": "ok",
                        "error": "",
                    }
                    for name, samples in sorted(timings.items())
                ]
                click.echo(f"  {len(rows)} benchmarks x {runs} runs")
            except (
                subprocess.CalledProcessError,
                OSError,
                RuntimeError,
                ValueError,
                BenchmarkSkipped,
            ) as exc:
                rows = [error_row(common, exc)]
                click.echo(f"  {rows[0]['status'].upper()}: {rows[0]['error']}")

            writer.writerows(rows)
            stream.flush()  # Preserve successful results if a later commit fails.

    click.echo(f"Results: {output}")


if __name__ == "__main__":
    main()
