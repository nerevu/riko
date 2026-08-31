# vim: sw=4:ts=4:expandtab
"""
Optional-extra degradation contract.

These assertions run **unmarked** in every environment and adapt to what is
installed: they assert the value the code exposes *with* an extra and the
fallback it exposes *without* it. That is what lets the base (no-extras) tox env
verify degraded behaviour rather than merely skipping the extra-only tests.

Parity checks ("fallback output equals fast-path output") need both libraries at
once, so they belong in the optional env; here we only pin each side's own
contract.
"""

import importlib.util

from riko.collections import list_targets
from riko.parsers import IJSON_IS_NATIVE, IS_FASTFEEDPARSER, IS_LXML


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def test_capability_flags_track_installed_libs():
    """The parser capability flags reflect whether each perf lib is importable."""
    assert IS_LXML is _installed("lxml")
    assert IS_FASTFEEDPARSER is _installed("fastfeedparser")

    if not _installed("ijson"):
        assert IJSON_IS_NATIVE is False


def test_finance_targets_track_csv2ofx():
    """``ofx``/``qif`` export targets appear only when the finance extra is present."""
    finance_targets = {"ofx", "qif"}
    targets = set(list_targets())

    if _installed("csv2ofx"):
        assert finance_targets <= targets
    else:
        assert not (finance_targets & targets)
