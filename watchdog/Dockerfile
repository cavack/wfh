ARG PYTHON_VERSION=3.14
ARG PYTHON_IMAGE=python:3.14-alpine@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc
FROM ${PYTHON_IMAGE}
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG VERSION=development
LABEL org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/cavack/wfh" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}"
RUN addgroup -S watchdog && adduser -S watchdog -G watchdog
WORKDIR /app

ENV HOME="/tmp" \
    TMPDIR="/tmp" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY main.py .
RUN chown -R watchdog:watchdog /app

USER watchdog
CMD ["python", "main.py"]
