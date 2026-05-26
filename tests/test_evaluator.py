"""Unit tests for the SLO evaluator and error budget calculation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from slo_manager.evaluator import SLOEvaluator
from slo_manager.models import SLODefinition, SLOType


def _make_slo(target: float = 0.999, window_days: int = 30) -> SLODefinition:
    return SLODefinition(
        name="test-slo",
        service="test-service",
        slo_type=SLOType.AVAILABILITY,
        target=target,
        window_days=window_days,
        prometheus_good_query="good_query",
        prometheus_total_query="total_query",
    )


def _make_evaluator(good: float, total: float) -> SLOEvaluator:
    client = MagicMock()
    client.query.side_effect = lambda q, **_: good if "good" in q else total
    return SLOEvaluator(client)


class TestSLIComputation:
    def test_perfect_sli(self) -> None:
        evaluator = _make_evaluator(good=1000, total=1000)
        status = evaluator.evaluate(_make_slo(target=0.999))
        assert status.current_sli == pytest.approx(1.0)

    def test_sli_at_target(self) -> None:
        evaluator = _make_evaluator(good=999, total=1000)
        status = evaluator.evaluate(_make_slo(target=0.999))
        assert status.current_sli == pytest.approx(0.999, rel=1e-3)
        assert status.meets_target

    def test_sli_below_target(self) -> None:
        evaluator = _make_evaluator(good=990, total=1000)
        status = evaluator.evaluate(_make_slo(target=0.999))
        assert status.current_sli == pytest.approx(0.99, rel=1e-3)
        assert not status.meets_target

    def test_zero_total_returns_sli_one(self) -> None:
        evaluator = _make_evaluator(good=0, total=0)
        status = evaluator.evaluate(_make_slo())
        assert status.current_sli == 1.0


class TestErrorBudget:
    def test_budget_fully_remaining(self) -> None:
        evaluator = _make_evaluator(good=1000, total=1000)
        status = evaluator.evaluate(_make_slo(target=0.999, window_days=30))
        budget = status.error_budget

        window_minutes = 30 * 24 * 60  # 43200
        assert budget.allowed_bad_minutes == pytest.approx((1 - 0.999) * window_minutes, rel=1e-3)
        assert budget.remaining_percent == pytest.approx(100.0, rel=0.01)

    def test_budget_partially_consumed(self) -> None:
        # SLI = 0.998 → error rate = 0.002 (target allows 0.001)
        evaluator = _make_evaluator(good=998, total=1000)
        status = evaluator.evaluate(_make_slo(target=0.999, window_days=30))
        budget = status.error_budget

        assert budget.consumed_bad_minutes > budget.allowed_bad_minutes
        assert budget.remaining_minutes < 0  # over budget
        assert budget.is_exhausted

    def test_budget_half_consumed(self) -> None:
        # SLI = 0.9995 → half the error budget consumed
        evaluator = _make_evaluator(good=9995, total=10000)
        status = evaluator.evaluate(_make_slo(target=0.999, window_days=30))
        budget = status.error_budget

        assert budget.remaining_percent == pytest.approx(50.0, rel=0.05)
        assert budget.status == "healthy"

    def test_budget_status_warning(self) -> None:
        # SLI = 0.9992 → ~80% consumed
        evaluator = _make_evaluator(good=9992, total=10000)
        status = evaluator.evaluate(_make_slo(target=0.999, window_days=30))
        assert status.error_budget.status in ("warning", "critical")

    def test_budget_status_critical(self) -> None:
        evaluator = _make_evaluator(good=9989, total=10000)
        status = evaluator.evaluate(_make_slo(target=0.999, window_days=30))
        # remaining < 10% → critical or exhausted
        assert status.error_budget.remaining_percent < 10


class TestBurnRateAlerts:
    def test_no_alerts_when_healthy(self) -> None:
        evaluator = _make_evaluator(good=9999, total=10000)
        status = evaluator.evaluate(_make_slo(target=0.999))
        firing = [a for a in status.burn_rate_alerts if a.firing]
        assert not firing

    def test_alerts_list_has_expected_rules(self) -> None:
        evaluator = _make_evaluator(good=9999, total=10000)
        status = evaluator.evaluate(_make_slo(target=0.999))
        # Should have 3 burn rate rules (fast, slow-6h, slow-3d)
        assert len(status.burn_rate_alerts) == 3

    def test_alert_thresholds_are_correct(self) -> None:
        evaluator = _make_evaluator(good=9999, total=10000)
        status = evaluator.evaluate(_make_slo(target=0.999))
        thresholds = {a.threshold for a in status.burn_rate_alerts}
        assert thresholds == {14.4, 6.0, 3.0}
