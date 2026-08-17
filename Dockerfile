# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────
# Stage 1: builder — resolve and install dependencies
#
# Anything needed only to *build* the environment stays in this stage and is
# discarded: compilers, headers, pip's caches. Only the finished virtualenv is
# carried forward.
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Never a floating tag such as :latest. A pinned digest-stable tag means a
# rebuild six months from now produces the same base, not whatever was
# published in the meantime.

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copied before the application code on purpose. Docker caches each layer and
# invalidates every layer after the first change it detects. Requirements
# change rarely, source code changes constantly — in this order, editing a
# router reuses the cached install instead of re-downloading every package.
COPY requirements.txt .

# --no-cache-dir: the wheel cache would be written into this layer and then
# thrown away with the stage. Not writing it keeps the build lean either way.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────
# Stage 2: runtime — what actually ships
#
# A fresh slim base. Nothing from the builder crosses over except the
# virtualenv, so pip's caches and any build tooling never reach production.
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# The result of the build, not the machinery that produced it.
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    # Send logs straight to the stream instead of buffering them. Without this,
    # `docker logs` stays empty until the buffer fills — which is exactly when
    # you are trying to diagnose a container that just died.
    PYTHONUNBUFFERED=1 \
    # No .pyc files: they would be written on every start into a layer that is
    # discarded when the container stops.
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Create the unprivileged user before copying, so ownership is set in one step.
# A process that escapes the application lands as a user that owns nothing and
# can install nothing, rather than as root inside the container.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY --chown=appuser:appuser app/ ./app/

USER appuser

# Documents the port for readers and tooling. It publishes nothing by itself;
# `-p` at run time does that.
EXPOSE 8000

# Compose uses this to decide when the container is ready to receive traffic.
# It hits /health, which queries the database — so a container that is running
# but cannot reach PostgreSQL reports unhealthy instead of accepting requests
# it would only fail.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=2).status == 200 else 1)"

# Exec form, not shell form: uvicorn becomes PID 1 and receives SIGTERM
# directly, so `docker stop` shuts it down gracefully instead of waiting out
# the ten-second timeout and killing it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
