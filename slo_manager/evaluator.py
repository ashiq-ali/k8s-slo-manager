"""Prometheus query engine and SLO evaluation logic."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .models import ErrorBudget, SLODefinition, SLOStatus

logger = logging.getLogger(__name__)


class PrometheusClient:
    """Thin wrapper around the Prometheus HTTP API."""

    def __init__(self, url: str, timeout: int = 30) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def query(self, promql: str, time: datetime | None = None) -> float:
        """Execute an instant query and return the scalar result."""
        params: dict[str, Any] = {"query": promql}
        if time is not None:
            params["time"] = time.timestamp()

        resp = self._session.get(
            f"{self._url}/api/v1/query",
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        if data["status"] != "success":
            raise ValueError(f"Prometheus query failed: {data.get('error', 'unknown')}")

        results = data["data"]["result"]
        if not results:
            logger.warning("Query returned no results: %s", promql)
            return 0.0

        # Take the first result's value
        _, value = results[0]["value"]
        return float(value)

    def query_range(
        self,
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "5m",
    ) -> list[tuple[float, float]]:
        """Execute a range query and return (timestamp, value) pairs."""
        resp = self._session.get(
            f"{self._url}/api/v1/query_range",
            params={
                "query": promql,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        if data["status"] != "success":
            raise ValueError(f"Prometheus range query failed: {data.get('error', 'unknown')}")

        results = data["data"]["result"]
        if not results:
            return []

        return [(float(ts), float(v)) for ts, v in results[0]["values"]]


class SLOEvaluator:
    """Evaluates SLO definitions against live Prometheus data."""

    def __init__(self, prometheus_client: PrometheusClient) -> None:
        self._prom = prometheus_client

    def evaluate(self, slo: SLODefinition) -> SLOStatus:
        """Evaluate a single SLO and return its current status."""
        now = datetime.now(tz=timezone.utc)
        window_start = now - timedelta(days=slo.window_days)

        current_sli = self._compute_sli(slo, now)
        error_budget = self._compute_error_budget(slo, now, window_start, current_sli)

        from .burn_rate import BurnRateCalculator
        calculator = BurnRateCalculator(self._prom)
        alerts = calculator.compute_alerts(slo, now)

        healthy = current_sli >= slo.target and not error_budget.is_exhausted

        return SLOStatus(
            definition=slo,
            current_sli=current_sli,
            error_budget=error_budget,
            burn_rate_alerts=alerts,
            healthy=healthy,
        )

    def _compute_sli(self, slo: SLODefinition, at: datetime) -> float:
        """Compute the current SLI value: good_events / total_events."""
        good = self._prom.query(slo.prometheus_good_query, time=at)
        total = self._prom.query(slo.prometheus_total_query, time=at)

        if total == 0:
            logger.warning("Total events = 0 for SLO '%s'; returning SLI=1.0", slo.name)
            return 1.0

        return good / total

    def _compute_error_budget(
        self,
        slo: SLODefinition,
        now: datetime,
        window_start: datetime,
        current_sli: float,
    ) -> ErrorBudget:
        """Calculate error budget consumption over the rolling window."""
        window_minutes = slo.window_days * 24 * 60

        # How many bad minutes are allowed in the window?
        allowed_bad_minutes = (1 - slo.target) * window_minutes

        # Estimate consumed bad minutes from the measured SLI
        actual_bad_fraction = max(0.0, 1 - current_sli)
        consumed_bad_minutes = actual_bad_fraction * window_minutes

        remaining_minutes = allowed_bad_minutes - consumed_bad_minutes
        remaining_percent = (
            (remaining_minutes / allowed_bad_minutes * 100)
            if allowed_bad_minutes > 0
            else 0.0
        )
        burn_rate = (
            consumed_bad_minutes / allowed_bad_minutes if allowed_bad_minutes > 0 else 0.0
        )

        return ErrorBudget(
            slo_name=slo.name,
            target=slo.target,
            window_days=slo.window_days,
            total_minutes=window_minutes,
            allowed_bad_minutes=round(allowed_bad_minutes, 2),
            consumed_bad_minutes=round(consumed_bad_minutes, 2),
            remaining_minutes=round(remaining_minutes, 2),
            remaining_percent=round(remaining_percent, 2),
            burn_rate=round(burn_rate, 4),
        )
