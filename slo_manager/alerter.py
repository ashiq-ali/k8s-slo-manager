"""Send burn rate alerts to Slack and PagerDuty."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from .models import AlertSeverity, BurnRateAlert, SLOStatus

logger = logging.getLogger(__name__)


class SlackAlerter:
    """Posts burn rate alerts to a Slack webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook = webhook_url

    def send_alerts(self, statuses: list[SLOStatus]) -> None:
        for status in statuses:
            for alert in status.burn_rate_alerts:
                if alert.firing:
                    self._post(alert)

    def _post(self, alert: BurnRateAlert) -> None:
        colour = "#FF0000" if alert.severity == AlertSeverity.PAGE else "#FFA500"
        icon = "🚨" if alert.severity == AlertSeverity.PAGE else "🎫"

        payload: dict[str, Any] = {
            "attachments": [
                {
                    "color": colour,
                    "title": f"{icon} SLO Burn Rate Alert — {alert.slo_name}",
                    "text": alert.message,
                    "fields": [
                        {"title": "Severity",   "value": alert.severity.value.upper(), "short": True},
                        {"title": "Burn Rate",  "value": f"{alert.burn_rate:.2f}×",    "short": True},
                        {"title": "Threshold",  "value": f"{alert.threshold}×",        "short": True},
                    ],
                    "footer": "k8s-slo-manager",
                }
            ]
        }

        try:
            resp = requests.post(self._webhook, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Slack alert sent for SLO '%s'", alert.slo_name)
        except requests.RequestException as exc:
            logger.error("Failed to send Slack alert: %s", exc)


class PagerDutyAlerter:
    """Triggers PagerDuty incidents for PAGE-severity burn rate alerts."""

    EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

    def __init__(self, integration_key: str) -> None:
        self._key = integration_key

    def send_alerts(self, statuses: list[SLOStatus]) -> None:
        for status in statuses:
            for alert in status.burn_rate_alerts:
                if alert.firing and alert.severity == AlertSeverity.PAGE:
                    self._trigger(alert)

    def _trigger(self, alert: BurnRateAlert) -> None:
        payload: dict[str, Any] = {
            "routing_key": self._key,
            "event_action": "trigger",
            "dedup_key": f"slo-burn-rate-{alert.slo_name}",
            "payload": {
                "summary": alert.message,
                "severity": "critical",
                "source": "k8s-slo-manager",
                "custom_details": {
                    "slo_name": alert.slo_name,
                    "burn_rate": alert.burn_rate,
                    "threshold": alert.threshold,
                },
            },
        }

        try:
            resp = requests.post(self.EVENTS_URL, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("PagerDuty incident triggered for SLO '%s'", alert.slo_name)
        except requests.RequestException as exc:
            logger.error("Failed to trigger PagerDuty incident: %s", exc)


def build_alerters() -> list[SlackAlerter | PagerDutyAlerter]:
    """Build alerters from environment variables."""
    alerters: list[Any] = []

    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        alerters.append(SlackAlerter(slack_url))
        logger.info("Slack alerter enabled")

    pd_key = os.getenv("PAGERDUTY_INTEGRATION_KEY")
    if pd_key:
        alerters.append(PagerDutyAlerter(pd_key))
        logger.info("PagerDuty alerter enabled")

    if not alerters:
        logger.warning("No alerters configured — set SLACK_WEBHOOK_URL or PAGERDUTY_INTEGRATION_KEY")

    return alerters
