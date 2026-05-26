"""CLI entry point: slo status | slo report | slo check | slo daemon."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import click

from .alerter import build_alerters
from .evaluator import PrometheusClient, SLOEvaluator
from .loader import load_slos
from .reporter import report_json, report_markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
DEFAULT_SLO_FILE = os.getenv("SLO_FILE", "examples/slos.yaml")


def _make_evaluator(prometheus_url: str) -> SLOEvaluator:
    client = PrometheusClient(prometheus_url)
    return SLOEvaluator(client)


@click.group()
@click.version_option()
def cli() -> None:
    """k8s-slo-manager — SLO tracking and error budget management for Kubernetes services."""


@cli.command()
@click.option("--slo-file", default=DEFAULT_SLO_FILE, show_default=True, help="Path to SLO YAML")
@click.option("--prometheus-url", default=DEFAULT_PROMETHEUS_URL, show_default=True)
@click.option("--output", type=click.Choice(["table", "json"]), default="table", show_default=True)
def status(slo_file: str, prometheus_url: str, output: str) -> None:
    """Show current SLI values and error budget status for all SLOs."""
    slos = load_slos(slo_file)
    evaluator = _make_evaluator(prometheus_url)

    statuses = []
    for slo in slos:
        try:
            s = evaluator.evaluate(slo)
            statuses.append(s)
        except Exception as exc:
            logger.error("Failed to evaluate SLO '%s': %s", slo.name, exc)

    if output == "json":
        click.echo(report_json(statuses))
        return

    # Table output
    click.echo(f"\n{'SLO':<30} {'Target':>8} {'SLI':>10} {'Budget%':>8} {'Status':<10}")
    click.echo("-" * 70)
    for s in statuses:
        budget = s.error_budget
        flag = "✅" if s.healthy else ("⚠️ " if budget.remaining_percent > 0 else "🔴")
        click.echo(
            f"{s.definition.name:<30} "
            f"{s.definition.target*100:>7.3f}% "
            f"{s.current_sli*100:>9.4f}% "
            f"{budget.remaining_percent:>7.1f}% "
            f"{flag}"
        )
    click.echo()


@cli.command()
@click.option("--slo-file", default=DEFAULT_SLO_FILE, show_default=True)
@click.option("--prometheus-url", default=DEFAULT_PROMETHEUS_URL, show_default=True)
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown", show_default=True)
@click.option("--out", type=click.Path(), default=None, help="Write report to file (default: stdout)")
def report(slo_file: str, prometheus_url: str, fmt: str, out: str | None) -> None:
    """Generate a full error budget report (Markdown or JSON)."""
    slos = load_slos(slo_file)
    evaluator = _make_evaluator(prometheus_url)
    statuses = [evaluator.evaluate(slo) for slo in slos]

    if fmt == "json":
        content = report_json(statuses)
        if out:
            Path(out).write_text(content)
            click.echo(f"Report written to {out}")
        else:
            click.echo(content)
    else:
        if out:
            with Path(out).open("w") as f:
                report_markdown(statuses, f)
            click.echo(f"Report written to {out}")
        else:
            report_markdown(statuses, sys.stdout)


@cli.command()
@click.option("--slo-file", default=DEFAULT_SLO_FILE, show_default=True)
@click.option("--prometheus-url", default=DEFAULT_PROMETHEUS_URL, show_default=True)
def check(slo_file: str, prometheus_url: str) -> None:
    """Exit non-zero if any SLO is breached (useful for CI gates)."""
    slos = load_slos(slo_file)
    evaluator = _make_evaluator(prometheus_url)
    statuses = [evaluator.evaluate(slo) for slo in slos]

    breached = [s for s in statuses if not s.meets_target]
    if breached:
        click.echo(f"❌ {len(breached)} SLO(s) breached:", err=True)
        for s in breached:
            click.echo(f"   {s.definition.name}: {s.current_sli*100:.4f}% < {s.definition.target*100:.3f}%", err=True)
        sys.exit(1)

    click.echo(f"✅ All {len(statuses)} SLO(s) within target")


@cli.command()
@click.option("--slo-file", default=DEFAULT_SLO_FILE, show_default=True)
@click.option("--prometheus-url", default=DEFAULT_PROMETHEUS_URL, show_default=True)
@click.option("--interval", default=60, show_default=True, help="Evaluation interval in seconds")
def daemon(slo_file: str, prometheus_url: str, interval: int) -> None:
    """Run as a daemon: evaluate SLOs on a schedule and fire alerts."""
    click.echo(f"Starting SLO daemon (interval={interval}s, slos={slo_file})")
    slos = load_slos(slo_file)
    evaluator = _make_evaluator(prometheus_url)
    alerters = build_alerters()

    while True:
        try:
            statuses = [evaluator.evaluate(slo) for slo in slos]
            for alerter in alerters:
                alerter.send_alerts(statuses)

            firing = sum(
                1 for s in statuses for a in s.burn_rate_alerts if a.firing
            )
            logger.info("Evaluated %d SLOs — %d alert(s) firing", len(slos), firing)
        except Exception as exc:
            logger.error("Daemon evaluation error: %s", exc)

        time.sleep(interval)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
