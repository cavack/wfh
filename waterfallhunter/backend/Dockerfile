# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# نصب ابزارهای پایه برای کامپایل پکیج‌های خاص
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt

# Stage 2: Production
FROM python:3.12-slim

WORKDIR /app

# تنظیم متغیرهای محیطی
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:${PATH}" \
    PYTHONPATH="/app/src"

# کپی کردن پکیج‌های نصب شده از استیج قبلی
COPY --from=builder /root/.local /root/.local

# ساخت دایرکتوری برای دیتابیس (Provider Registry)
RUN mkdir -p /app/data

# کپی کردن سورس کدهای پروژه
COPY ./src /app/src

# اجرای سرور به صورت پیش‌فرض
CMD ["uvicorn", "waterfallhunter.main:app", "--host", "0.0.0.0", "--port", "8000"]
