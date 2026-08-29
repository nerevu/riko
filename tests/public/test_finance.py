# vim: sw=4:ts=4:expandtab
"""
Finance-extra export tests (``csv2ofx``).

The ``ofx``/``qif`` export targets are registered only when the ``finance``
extra is installed, so these carry ``@pytest.mark.finance`` and are auto-skipped
when it is absent (see the collection hook in ``conftest.py``).
"""

import pytest

from riko.collections import Targets, export, list_targets

pytestmark = pytest.mark.finance

TRANSACTIONS = [
    {
        "Account": "Checking",
        "Date": "2024-01-01",
        "Amount": "100.00",
        "Description": "Acme",
        "Reference": "Widget",
        "Row": "1",
    },
    {
        "Account": "Checking",
        "Date": "2024-01-02",
        "Amount": "-50.00",
        "Description": "Store",
        "Reference": "Refund",
        "Row": "2",
    },
]


def test_finance_targets_registered():
    """The finance extra registers the ``ofx``/``qif`` export targets."""
    targets = list_targets()
    assert "ofx" in targets
    assert "qif" in targets


def test_export_ofx_serializes_transactions():
    """``export(..., Targets.OFX)`` emits an OFX document, one txn per record."""
    ofx = "".join(export(TRANSACTIONS, Targets.OFX))
    assert "<OFX>" in ofx
    assert ofx.count("<STMTTRN>") == len(TRANSACTIONS)


def test_export_qif_serializes_transactions():
    """``export(..., Targets.QIF)`` emits a QIF document for the transactions."""
    qif = "".join(export(TRANSACTIONS, Targets.QIF))
    assert qif.startswith("!Account")
    assert "Checking" in qif
