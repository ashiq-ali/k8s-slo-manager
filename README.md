# k8s-slo-manager

> SLO tracking, error budget calculation, and burn-rate alerting for Kubernetes services — built on the Google SRE workbook model.

[![CI](https://github.com/ashiq-ali/k8s-slo-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/ashiq-ali/k8s-slo-manager/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        k8s-slo-manager                          │
│                                                                  │
│  slos.yaml ──► Loader ──► SLOEvaluator ──► SLOStatus            │
│                                │                                 │
│                          PrometheusClient                        │
│                          (instant + range queries)               │
│                                │                                 │
│                     BurnRateCalculator                           │
│                     (fast/slow burn, 3 rule sets)                │
│                                │                                 │
│                    ┌───────────┴──────────┐                      │
│                    │                      │                      │
│               SlackAlerter         PagerDutyAlerter              │
│                    │                      │                      │
│              Reporter (MD/JSON)    PrometheusRule (YAML)         │
└─────────────────────────────────────────────────────────────────┘
```

## Burn Rate Model (Google SRE Workbook)

| Alert | Burn Rate | Short Window | Long Window | Severity | Budget consumed |
|-------|-----------|--------------|-------------|----------|-----------------|
| Fast burn | **14.4×** | 1h | 5m | 🚨 PAGE | 2% in 1h |
| Slow burn | **6×** | 6h | 30m | 🚨 PAGE | 5% in 6h |
| Very slow | **3×** | 3d | 6h | 🎫 TICKET | 10% in 3d |

A **burn rate** of 1.0 means you consume exactly the budget over the SLO window. Alerts fire only when **both** windows exceed the threshold, eliminating transient-spike false positives.

## Quickstart

```bash
pip install -e ".[dev]"

# Check all SLOs
slo status --slo-file examples/slos.yaml --prometheus-url http://localhost:9090

# Generate Markdown report
slo report --slo-file examples/slos.yaml --format markdown

# CI gate: exit non-zero if any SLO is breached
slo check --slo-file examples/slos.yaml

# Run as daemon with Slack alerts
SLACK_WEBHOOK_URL=https://hooks.slack.com/... slo daemon --interval 60
```

## SLO Definition Format

```yaml
# examples/slos.yaml
slos:
  - name: checkout-availability
    service: checkout
    type: availability       # availability | latency | error_rate | throughput
    target: 0.999            # 99.9%
    window_days: 30
    prometheus_good_query: >
      sum(rate(http_requests_total{job="checkout",code!~"5.."}[5m]))
      / sum(rate(http_requests_total{job="checkout"}[5m]))
    prometheus_total_query: >
      sum(rate(http_requests_total{job="checkout"}[5m]))
```

## Deploy to Kubernetes

```bash
# Apply daemon deployment
kubectl apply -f k8s/deployment.yaml

# Apply PrometheusRule (requires prometheus-operator)
kubectl apply -f k8s/prometheusrule.yaml

# Import Grafana dashboard
# In Grafana: Dashboards → Import → Upload k8s/grafana-dashboard.json
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `slo status` | Table view of current SLI and error budget |
| `slo report` | Full Markdown or JSON error budget report |
| `slo check` | Exit non-zero if any SLO is breached (CI gate) |
| `slo daemon` | Run continuously, evaluate and alert on interval |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PROMETHEUS_URL` | Prometheus endpoint (default: `http://localhost:9090`) |
| `SLO_FILE` | Path to SLO YAML (default: `examples/slos.yaml`) |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook for alerts |
| `PAGERDUTY_INTEGRATION_KEY` | PagerDuty Events v2 integration key |

## Development

```bash
pip install -e ".[dev]"
pytest                  # run tests with coverage
ruff check .            # lint
mypy slo_manager        # type check
```

## Tech Stack

**Python · Prometheus · Kubernetes · Grafana · Slack · PagerDuty**
