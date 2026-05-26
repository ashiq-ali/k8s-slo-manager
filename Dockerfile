FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ashiq-ali/k8s-slo-manager"
LABEL org.opencontainers.image.description="SLO tracking and error budget management for Kubernetes"

RUN groupadd -r slo && useradd -r -g slo slo

WORKDIR /app
COPY --from=builder /app/dist/*.whl .
RUN pip install --no-cache-dir *.whl && rm *.whl

USER slo
ENTRYPOINT ["slo"]
CMD ["--help"]
