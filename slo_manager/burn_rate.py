"""Fast/slow burn rate detection per the Google SRE workbook model.

Google SRE burn-rate alert rules (Chapter 5):
  - Fast burn:  14.4× over 1h / 5m  → page  (burns 2% budget in 1h)
  - Slow burn:   6.0× over 6h / 30m → page  (burns 5% budget in 6h)
  - Slow burn:   3.0× over 3d / 6h  → ticket (burns 10% budget in 3 days)

A "burn rate" is: (error_rate_now) / (1 - slo_target).
A burn rate of 1.0 means you're consuming budget at exactly the rate that
exhausts it at the end of the window.  14.4× means you exhaust it in 1/14.4
of the window — for a 30-day window that's ~2 days.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .models import AlertSeverity, BurnRateAlert, SLODefinition

logger = logging.getLogger(__name__)


# (burn_rate_threshold, short_window_minutes, long_window_minutes, severity, label)
BURN_RATE_RULES: list[tuple[float, int, int, AlertSeverity, str]] = [
    (14.4, 60,   5,   AlertSeverity.PAGE,   "fast_burn"),
    (6.0,  360,  30,  AlertSeverity.PAGE,   "slow_burn_6h"),
    (3.0,  4320, 360, AlertSeverity.TICKET, "slow_burn_3d"),
]


class BurnRateCalculator:
    def __init__(self, prometheus_client: "PrometheusClient") -> None:  # noqa: F821
        self._prom = prometheus_client

    def compute_alerts(self, slo: SLODefinition, now: datetime) -> list[BurnRateAlert]:
        alerts: list[BurnRateAlert] = []

        for threshold, short_min, long_min, severity, label in BURN_RATE_RULES:
            short_rate = self._burn_rate(slo, now, short_min)
            long_rate = self._burn_rate(slo, now, long_min)

            # Alert fires only when BOTH windows are burning above threshold
            # (reduces false positives from transient spikes)
            firing = short_rate >= threshold and long_rate >= threshold

            alerts.append(
                BurnRateAlert(
                    slo_name=slo.name,
                    severity=severity,
                    burn_rate=round(short_rate, 3),
                    threshold=threshold,
                    window_short_minutes=short_min,
                    window_long_minutes=long_min,
                    firing=firing,
                    message=(
                        f"[{label}] '{slo.name}' burn rate {short_rate:.2f}× "
                        f"(threshold {threshold}×) — "
                        f"short window {short_min}m burn={short_rate:.2f}, "
                        f"long window {long_min}m burn={long_rate:.2f}"
                    ),
                )
            )

        return alerts

    def _burn_rate(self, slo: SLODefinition, now: datetime, window_minutes: int) -> float:
        """Compute the burn rate over the given window."""
        window = f"{window_minutes}m"
        bad_rate = self._error_rate(slo, window)
        allowed_error_rate = 1 - slo.target

        if allowed_error_rate == 0:
            return 0.0

        return bad_rate / allowed_error_rate

    def _error_rate(self, slo: SLODefinition, window: str) -> float:
        """Query the fraction of bad events over a PromQL range window."""
        # Wrap user queries in rate() over the window
        bad_query = f"1 - ({slo.prometheus_good_query})"
        try:
            return self._prom.query(bad_query)
        except Exception as exc:
            logger.warning("Could not compute error rate for '%s': %s", slo.name, exc)
            return 0.0
