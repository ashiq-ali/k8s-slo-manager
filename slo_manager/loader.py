"""Load SLO definitions from YAML files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .models import LatencyTarget, SLODefinition, SLOType

logger = logging.getLogger(__name__)


def load_slos(path: str | Path) -> list[SLODefinition]:
    """Load one or more SLO definitions from a YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"SLO config not found: {p}")

    with p.open() as f:
        data = yaml.safe_load(f)

    slos_raw: list[dict[str, Any]] = data.get("slos", [])
    slos = [_parse_slo(raw) for raw in slos_raw]
    logger.info("Loaded %d SLO definitions from %s", len(slos), p)
    return slos


def _parse_slo(raw: dict[str, Any]) -> SLODefinition:
    latency_raw = raw.get("latency_target")
    latency_target = (
        LatencyTarget(
            threshold_ms=latency_raw["threshold_ms"],
            percentile=latency_raw["percentile"],
        )
        if latency_raw
        else None
    )

    return SLODefinition(
        name=raw["name"],
        service=raw["service"],
        slo_type=SLOType(raw["type"]),
        target=raw["target"],
        window_days=raw.get("window_days", 30),
        prometheus_good_query=raw["prometheus_good_query"],
        prometheus_total_query=raw["prometheus_total_query"],
        description=raw.get("description", ""),
        labels=raw.get("labels", {}),
        latency_target=latency_target,
    )
