# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────
# Stage 1: builder
# Same split as the API image, for the same reason: build tooling and pip's
# caches stay here and never reach what ships.
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

COPY agent/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────
# Stage 2: runtime
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin agentuser

COPY --chown=agentuser:agentuser agent/agent.py .

USER agentuser

# No EXPOSE and no HEALTHCHECK: the agent listens on nothing and answers
# nothing, so there is no endpoint for Docker to probe. Its health is observed
# from the other side — an agent that stops reporting is exactly what the API
# renders as STALE and then OFFLINE. That is the system's own monitoring, and
# duplicating it here would add nothing.

CMD ["python", "agent.py"]
