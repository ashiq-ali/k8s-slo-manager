"""Data models for SLO definitions and evaluation results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SLOType(str, Enum):
    AVAILABILITY = "availability"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"


class AlertSeverity(str, Enum):
    PAGE = "page"      # fast burn — wake someone up
    TICKET = "ticket"  # slow burn — create a ticket


@dataclass(frozen=True)
class LatencyTarget:
    threshold_ms: float   # e.g. 200
    percentile: float     # e.g. 0.99 for p99


@dataclass(frozen=True)
class SLODefinition:
    name: str
    service: str
    slo_type: SLOType
    target: float                    # 0.0–1.0 (e.g. 0.999 = 99.9%)
    window_days: int                 # rolling window in days (typically 30)
    prometheus_good_query: str       # numerator: good events
    prometheus_total_query: str      # denominator: total events
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    latency_target: Optional[LatencyTarget] = None


@dataclass
class ErrorBudget:
    slo_name: str
    target: float                   # e.g. 0.999
    window_days: int
    total_minutes: float            # window in minutes
    allowed_bad_minutes: float      # budget = (1 - target) * window
    consumed_bad_minutes: float     # actual bad minutes so far
    remaining_minutes: float        # budget - consumed
    remaining_percent: float        # remaining / allowed * 100
    burn_rate: float                # current consumption rate vs allowed

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_minutes <= 0

    @property
    def status(self) -> str:
        if self.remaining_percent >= 50:
            return "healthy"
        if self.remaining_percent >= 10:
            return "warning"
        return "critical"


@dataclass
class BurnRateAlert:
    slo_name: str
    severity: AlertSeverity
    burn_rate: float
    threshold: float
    window_short_minutes: int
    window_long_minutes: int
    message: str
    firing: bool


@dataclass
class SLOStatus:
    definition: SLODefinition
    current_sli: float              # measured SLI value right now
    error_budget: ErrorBudget
    burn_rate_alerts: list[BurnRateAlert]
    healthy: bool

    @property
    def meets_target(self) -> bool:
        return self.current_sli >= self.definition.target
