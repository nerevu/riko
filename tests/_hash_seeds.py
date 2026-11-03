# vim: sw=4:ts=4:expandtab
"""
Pytest plugin that runs one probe interpreter per hash seed for the whole session.

Every result that must not depend on ``PYTHONHASHSEED`` (a canonical digest, the
ambiguous time zone abbreviations, graph orders, a written set, the ``hash`` module)
is computed by one script, once under each seed in ``HASH_SEEDS``. The
``hash_seed_probes`` fixture maps each seed to that run's results, so each test
compares its own slice across seeds without launching interpreters of its own.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests import run_python

if TYPE_CHECKING:
    from pathlib import Path

HASH_SEEDS = ("0", "4242")

PROBE_SCRIPT = """
import json
import sys
from pathlib import Path

from riko.base._dateutils import TZINFOS
from riko.base._graph import scc_sort, topological_sort
from riko.coercion._canonical import IdentityDomain, digest
from riko.modules.hash import pipe as hash_pipe
from riko.modules.write import pipe as write_pipe

value = {
    "text": ["a", "b", "c"],
    "raw": (b"x", b"yz"),
    "tags": {"red", "green", "blue", "cyan"},
    "frozen": frozenset({"k1", "k2", "k3"}),
    "nested": {"inner": {"s": {"p", "q"}, "b": b"\\x00"}},
}
orders = [
    topological_sort({"a": {"b"}, "b": {"a"}, "c": set()}),
    topological_sort({"a": {"b", "c", "d"}, "e": {"f", "g"}}),
    scc_sort({"A": {"B", "C"}, "B": {"D"}, "C": {"D"}, "D": {"E"}}),
]
dest = Path(sys.argv[1])
items = [{"tags": {"alpha", "beta", "gamma", "delta"}}]
list(write_pipe(items, conf={"dest": str(dest), "fmt": "json"}))
probes = {
    "digest": digest(value, IdentityDomain.FINGERPRINT),
    "zones": [str(TZINFOS[key]) for key in ("IST", "AST", "EET", "WAT")],
    "orders": [str(order) for order in orders],
    "set_write": dest.read_text(),
    "hash": next(hash_pipe({"content": "hello world"}))["hash"],
}
print(json.dumps(probes))
"""


def _load_probes(seed: str, dest: Path) -> dict[str, object]:
    """Loads one probe interpreter's results under ``seed``."""
    return json.loads(run_python("-c", PROBE_SCRIPT, str(dest), hash_seed=seed).stdout)


@pytest.fixture(scope="session")
def hash_seed_probes(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, object]]:
    tmp_path = tmp_path_factory.mktemp("hash-seeds")
    return {seed: _load_probes(seed, tmp_path / f"{seed}.json") for seed in HASH_SEEDS}
