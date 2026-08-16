# Stage 1: Builder
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production
FROM python:3.12-slim
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
