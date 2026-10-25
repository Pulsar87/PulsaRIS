FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Retry/force-unsafe-io guard against transient Debian mirror failures (exit 100)
RUN apt-get -o Acquire::Retries=5 -o DPkg.Use-SafeIO=false update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        libpq-dev gcc curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# PACS Task 4.3: fetch the pinned OHIF viewer bundle ONCE at build time into
# static/ohif/ (integrity-verified against unpkg's published sha256). It is
# then served same-origin by Django/WhiteNoise — no CDN at runtime. Build
# without network? Pre-place static/ohif/index.umd.js and this step no-ops.
COPY . .
RUN python manage.py pacs_fetch_ohif || \
    echo "WARNING: OHIF bundle fetch failed; viewer page will show setup instructions." >&2
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Run entrypoint first, then pass CMD to it
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
