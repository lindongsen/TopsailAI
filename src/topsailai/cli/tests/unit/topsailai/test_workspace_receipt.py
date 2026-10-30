"""Tests for the shared workspace JSON receipt boundary.

Author: DawsonLin
"""

import json

import pytest

from cli_topsailai import workspace_receipt as receipts


def test_json_requested_ignores_consumed_values():
    """A value that happens to be ``--json`` must not enable JSON mode."""
    assert receipts.json_requested(["--json"]) is True
    assert receipts.json_requested(["folder", "--json"]) is True
    assert receipts.json_requested(["-m", "--json"]) is False
    assert receipts.json_requested(["-s", "--json"]) is False
    assert receipts.json_requested(["--", "--json"]) is False
    assert receipts.json_requested([]) is False


def test_new_receipt_publishes_the_complete_field_set():
    """Every receipt carries the same stable public fields."""
    receipt = receipts.new_receipt("kill", session_id="s1", pid=7)
    assert tuple(receipt) == receipts.RECEIPT_FIELDS
    assert receipt["ok"] is False
    assert receipt["exit_code"] == 2
    assert receipt["delivery_state"] is None
    assert receipt["delivery_unknown"] is False


def test_settle_classifies_success_and_documented_failures():
    """Only zero is success; documented codes map to their named error."""
    success = receipts.settle(
        receipts.new_receipt("kill"), 0, receipts.KILL_ERROR_CODES, message="done")
    assert success["ok"] is True
    assert success["error_code"] is None
    assert success["message"] == "done"

    failure = receipts.settle(
        receipts.new_receipt("kill"), 3, receipts.KILL_ERROR_CODES)
    assert failure["ok"] is False
    assert failure["error_code"] == "target_error"
    assert failure["delivery_unknown"] is False


def test_settle_preserves_observed_child_status():
    """An observed child status is not flattened into a generic failure."""
    receipt = receipts.settle(
        receipts.new_receipt("agent"), 42, receipts.AGENT_ERROR_CODES)
    assert receipt["error_code"] == "child_exit_status"
    assert receipt["exit_code"] == 42


def test_settle_rejects_non_process_status_as_child_exit():
    """Negative and out-of-range values are generic command failures."""
    for status in (-1, 256):
        receipt = receipts.settle(
            receipts.new_receipt("agent"), status, receipts.AGENT_ERROR_CODES)
        assert receipt["error_code"] == "command_failed"


def test_settle_marks_only_unresolved_custody_as_unknown():
    """Delivery is unknown only when custody could not be proven."""
    assert receipts.settle(
        receipts.new_receipt("agent"), 6, receipts.AGENT_ERROR_CODES
    )["delivery_unknown"] is True
    assert receipts.settle(
        receipts.new_receipt("agent"), 5, receipts.AGENT_ERROR_CODES
    )["delivery_unknown"] is False


def test_emit_receipt_writes_exactly_one_document(capsys):
    """The emitted payload is one parseable document with no extra fields."""
    receipt = receipts.new_receipt("kill", session_id="s1", pid=7)
    receipt.update(ok=True, exit_code=0, delivery_state="signal_sent")
    receipts.emit_receipt(receipt)
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    payload = json.loads(output)
    assert tuple(payload) == receipts.RECEIPT_FIELDS
    assert payload["delivery_state"] == "signal_sent"


def test_emit_failure_reports_not_delivered(capsys):
    """A request that never executed is reported as not delivered."""
    receipts.emit_failure("resume", 3, "session_not_found", "missing",
                          session_id="s1")
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["exit_code"] == 3
    assert payload["error_code"] == "session_not_found"
    assert payload["delivery_state"] == "not_delivered"
    assert payload["session_id"] == "s1"


@pytest.mark.parametrize("action, mapping", [
    ("kill", receipts.KILL_ERROR_CODES),
    ("agent", receipts.AGENT_ERROR_CODES),
    ("resume", receipts.RESUME_ERROR_CODES),
])
def test_error_code_maps_cover_documented_exit_codes(action, mapping):
    """Each command names every failure code it can actually return."""
    assert mapping[2] == "usage_error"
    assert 0 not in mapping
    # Custody and cancellation only exist where a launch owns a child.
    if action == "kill":
        assert 6 not in mapping
        assert 130 not in mapping
    else:
        assert mapping[6] == "custody_unresolved"
        assert mapping[130] == "cancelled"
