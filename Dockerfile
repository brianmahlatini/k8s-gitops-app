# syntax=docker/dockerfile:1.7
# ---- build: resolve and compile dependencies into an isolated venv --------
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --require-virtualenv -r requirements.txt && pip uninstall -y pip

# ---- runtime: no compilers, no pip cache, non-root, read-only friendly ------
FROM python:3.12-slim AS runtime
ARG APP_VERSION=dev
LABEL org.opencontainers.image.source="https://github.com/brianmahlatini/k8s-gitops-app" \
      org.opencontainers.image.description="Demo service for the GitOps delivery pipeline" \
      org.opencontainers.image.licenses="MIT"
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}
# Apply OS security fixes published since the base image was built, and drop
# pip/setuptools from the runtime: nothing installs packages at runtime, and
# fewer packages means fewer CVEs to triage.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall -y pip setuptools wheel || true
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
COPY --chown=root:root app ./app
USER 10001:10001
EXPOSE 8080
# exec form (no shell wrapper): uvicorn is PID 1 and receives SIGTERM directly
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--timeout-graceful-shutdown", "20"]
