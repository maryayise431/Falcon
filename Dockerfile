# ---- Builder stage: install Python deps ----
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps needed for psycopg2-binary / pillow at compile time
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Final runtime stage ----
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=falcon_project.settings

WORKDIR /app

# Copy the installed site-packages from the builder
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code (excludes secrets via .dockerignore)
COPY . .

# Non-root user for better security
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R appuser:appuser /app
USER appuser

# Collection of static files happens at build (no DB required)
RUN python manage.py collectstatic --noinput 2>/dev/null || echo "collectstatic skipped"

EXPOSE 8000

# Render injects the PORT env var; fall back to 8000 for local testing
CMD ["sh", "-c", "gunicorn falcon_project.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --timeout 120"]
