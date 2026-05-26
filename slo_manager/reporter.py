"""Generate SLO status reports in Markdown and JSON formats."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TextIO

from .models import SLOStatus


STATUS_EMOJI = {
    "healthy": "✅",
    "warning": "⚠️",
    "critical": "🔴",
}

SEVERITY_EMOJI = {
    "page": "🚨",
    "ticket": "🎫",
}


def report_markdown(statuses: list[SLOStatus], out: TextIO) -> None:
    """Write a Markdown error budget report."""
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    out.write(f"# SLO Error Budget Report\n\n")
    out.write(f"_Generated: {now}_\n\n")
    out.write("---\n\n")

    for status in statuses:
        slo = status.definition
        budget = status.error_budget
        emoji = STATUS_EMOJI.get(budget.status, "❓")

        out.write(f"## {emoji} {slo.name}\n\n")
        out.write(f"**Service:** `{slo.service}`  \n")
        out.write(f"**Description:** {slo.description or 'N/A'}  \n")
        out.write(f"**Window:** {slo.window_days} days  \n\n")

        # SLI / Target table
        sli_pct = status.current_sli * 100
        target_pct = slo.target * 100
        diff = sli_pct - target_pct
        meets = "✅" if status.meets_target else "❌"

        out.write("### SLI vs Target\n\n")
        out.write("| Metric | Value |\n")
        out.write("|--------|-------|\n")
        out.write(f"| Target | {target_pct:.3f}% |\n")
        out.write(f"| Current SLI | {sli_pct:.4f}% {meets} |\n")
        out.write(f"| Delta | {diff:+.4f}% |\n\n")

        # Error budget table
        out.write("### Error Budget\n\n")
        out.write("| Metric | Value |\n")
        out.write("|--------|-------|\n")
        out.write(f"| Allowed downtime | {budget.allowed_bad_minutes:.1f} min |\n")
        out.write(f"| Consumed | {budget.consumed_bad_minutes:.1f} min |\n")
        out.write(f"| Remaining | {budget.remaining_minutes:.1f} min |\n")
        out.write(f"| Remaining % | {budget.remaining_percent:.1f}% |\n")
        out.write(f"| Burn rate | {budget.burn_rate:.2f}× |\n\n")

        # Burn rate alerts
        firing_alerts = [a for a in status.burn_rate_alerts if a.firing]
        if firing_alerts:
            out.write("### 🔥 Active Burn Rate Alerts\n\n")
            for alert in firing_alerts:
                sev_emoji = SEVERITY_EMOJI.get(alert.severity.value, "⚠️")
                out.write(f"- {sev_emoji} **{alert.severity.value.upper()}** — {alert.message}\n")
            out.write("\n")
        else:
            out.write("### Burn Rate Alerts\n\n")
            out.write("_No alerts firing._\n\n")

        out.write("---\n\n")


def report_json(statuses: list[SLOStatus]) -> str:
    """Return a JSON report as a string."""
    now = datetime.now(tz=timezone.utc).isoformat()

    report = {
        "generated_at": now,
        "slos": [],
    }

    for status in statuses:
        slo = status.definition
        budget = status.error_budget

        report["slos"].append({  # type: ignore[union-attr]
            "name": slo.name,
            "service": slo.service,
            "type": slo.slo_type.value,
            "target_pct": slo.target * 100,
            "current_sli_pct": status.current_sli * 100,
            "meets_target": status.meets_target,
            "healthy": status.healthy,
            "error_budget": {
                "window_days": budget.window_days,
                "allowed_minutes": budget.allowed_bad_minutes,
                "consumed_minutes": budget.consumed_bad_minutes,
                "remaining_minutes": budget.remaining_minutes,
                "remaining_percent": budget.remaining_percent,
                "burn_rate": budget.burn_rate,
                "status": budget.status,
            },
            "burn_rate_alerts": [
                {
                    "severity": a.severity.value,
                    "firing": a.firing,
                    "burn_rate": a.burn_rate,
                    "threshold": a.threshold,
                    "message": a.message,
                }
                for a in status.burn_rate_alerts
            ],
        })

    return json.dumps(report, indent=2)
