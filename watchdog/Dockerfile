FROM python:3.14-alpine
RUN addgroup -S watchdog && adduser -S watchdog -G watchdog
WORKDIR /app

ENV HOME="/tmp" \
    TMPDIR="/tmp" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir httpx

COPY main.py .
RUN sed -i 's/127.0.0.1/waterfall-backend/g' main.py
RUN chown -R watchdog:watchdog /app

USER watchdog
CMD ["python", "main.py"]
