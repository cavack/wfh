ARG PYTHON_VERSION=3.14
ARG PYTHON_IMAGE=python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

# Stage 1: Builder
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Stage 2: Production
FROM ${PYTHON_IMAGE} AS production
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG VERSION=development
LABEL org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/cavack/wfh" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}"
RUN groupadd -r waterfall && useradd -r -g waterfall -d /app waterfall
WORKDIR /app

COPY --from=builder --chown=waterfall:waterfall /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    HOME="/tmp" \
    TMPDIR="/tmp" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/src"

RUN mkdir -p /app/data && chown -R waterfall:waterfall /app/data
COPY --chown=waterfall:waterfall ./src /app/src

USER waterfall
EXPOSE 8000
CMD ["uvicorn", "waterfallhunter.main:app", "--host", "0.0.0.0", "--port", "8000"]
