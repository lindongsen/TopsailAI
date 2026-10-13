"""Resource-free C1 cleanup budget regressions. Author: DawsonLin."""

from dataclasses import FrozenInstanceError

import pytest

from topsailai.hooks.cleanup_budget import CleanupBudget, RecoveryPolicy, finite_deadline


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "1", None, 10**400])
def test_budget_invalid_deadline(value):
    """Reject invalid deadline representations without resource access."""
    with pytest.raises(ValueError):
        finite_deadline(value)


@pytest.mark.parametrize("mode", ["observation_only", "resume_owned_stop"])
def test_budget_policy_is_immutable(mode):
    """Accept only explicit policy values without changing initial horizons."""
    policy = RecoveryPolicy(mode)
    with pytest.raises(FrozenInstanceError):
        policy.mode = "other"
    assert policy.mode == mode


@pytest.mark.parametrize("mode", [None, True, "other"])
def test_budget_policy_rejects_unknown(mode):
    """Reject malformed policies rather than normalize them into authority."""
    with pytest.raises(ValueError):
        RecoveryPolicy(mode)


def test_budget_recovery_preserves_initial_horizons():
    """A fresh invocation horizon must not renew execution or initial cleanup."""
    budget = CleanupBudget(10, 10.3)
    assert budget.signal_deadline(12, RecoveryPolicy()) == 10.3
    assert budget.signal_deadline(12, RecoveryPolicy("resume_owned_stop")) == 12
    assert (budget.execution_deadline, budget.cleanup_deadline) == (10, 10.3)
    assert budget.initial_horizon(10.2) == 10.3
    with pytest.raises(FrozenInstanceError):
        budget.cleanup_deadline = 12


@pytest.mark.parametrize("allowance", [0, 0.1, 0.3, 1])
def test_budget_phase_reservations(allowance):
    """Reserve independent channel and bounded handback slices within one horizon."""
    phases = CleanupBudget(10, 10.3).phases(20, 20 + allowance)
    assert 20 <= phases.work_end <= phases.channels_end <= phases.handback_end
    assert phases.handback_end == 20 + allowance
    assert phases.handback_end - phases.channels_end <= 0.050000001
    assert phases.channels_end - phases.work_end == pytest.approx(allowance * 0.2)


def test_budget_expired_phases_grant_no_work():
    """An expired invocation cannot gain a positive phase allowance."""
    phases = CleanupBudget(10, 10.3).phases(20, 19)
    assert (phases.work_end, phases.channels_end, phases.handback_end) == (19, 19, 19)


def test_budget_rejects_cleanup_before_execution():
    """Reject inconsistent initial horizons at construction."""
    with pytest.raises(ValueError):
        CleanupBudget(10, 9)


def test_budget_numeric_detachment_and_invalid_policy():
    """Detach supported numbers and reject policy lookalikes before use."""
    assert finite_deadline(2) == 2.0
    budget = CleanupBudget(1, 2)
    with pytest.raises(ValueError):
        budget.signal_deadline(3, "resume_owned_stop")
    with pytest.raises(ValueError):
        budget.phases(-1e308, 1e308)
