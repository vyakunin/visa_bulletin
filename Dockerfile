# Multi-stage Dockerfile for Visa Bulletin Dashboard
# Optimized for size and security

FROM debian:bookworm-slim AS bazel-builder

# Install Bazel and build dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    python3 \
    python3-dev \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Bazelisk (automatically picks correct Bazel version)
RUN wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazelisk/releases/download/v1.19.0/bazelisk-linux-amd64 \
    && chmod +x /usr/local/bin/bazel

# Create non-root user for Bazel build with home directory
RUN groupadd -r builder && \
    useradd -r -g builder -m -d /home/builder builder && \
    mkdir -p /app && \
    chown -R builder:builder /app /home/builder

# Switch to non-root user for build
USER builder
WORKDIR /app

# Copy project files (will be owned by builder)
COPY --chown=builder:builder . .

# Build with Bazel as non-root user (required by rules_python)
RUN bazel build //:runserver //:migrate //:ingest

# Extract built artifacts
RUN mkdir -p /app/dist && \
    cp -r bazel-bin/* /app/dist/ && \
    cp -r lib /app/dist/ && \
    cp -r models /app/dist/ && \
    cp -r webapp /app/dist/ && \
    cp -r django_config /app/dist/ && \
    cp -r scripts /app/dist/ && \
    cp manage.py /app/dist/

# Production stage
FROM python:3.11-slim

# Security: Run as non-root user
RUN groupadd -r visabulletin && useradd -r -g visabulletin visabulletin

# Install runtime dependencies
# libpq5: PostgreSQL client library required by psycopg2-binary at runtime
# libgomp1: OpenMP runtime (libgomp.so.1) required by LightGBM — the GBM expert
#   the dispatch uses for 6m/12m-horizon predictions (forward multi-horizon
#   serving in refresh_bulletin). Without it those horizons fail with
#   "libgomp.so.1: cannot open shared object file".
RUN apt-get update && apt-get install -y \
    libpq5 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built artifacts from builder
COPY --from=bazel-builder /app/dist /app
COPY --from=bazel-builder /app/.bazelversion /app/
COPY requirements.txt /app/

# Install Python dependencies and verify critical packages are importable
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import psycopg2; import django; print('OK: psycopg2 + django importable')"

# Create necessary directories and ensure __init__.py for all Python packages.
# Bazel handles imports via runfiles, so __init__.py files are not in the repo
# (see the "No __init__.py Files" rule); standard Python/gunicorn needs them for
# package discovery at runtime, so we create them at image-build time.
#
# Use `touch` unconditionally — it succeeds whether the file exists or not. The
# previous variant (`test ! -f X && touch X`) propagated a non-zero exit code
# the first time any directory already had __init__.py, breaking the && chain.
RUN mkdir -p saved_pages logs static && \
    find /app/webapp /app/models /app/lib \
        -type d ! -path '*/__pycache__/*' \
        -exec sh -c 'touch "$1/__init__.py"' _ {} \; && \
    chown -R visabulletin:visabulletin /app

# Switch to non-root user
USER visabulletin

# Expose port
EXPOSE 8000

# Health check (Python-based; curl not guaranteed in slim image)
HEALTHCHECK --interval=10s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/', timeout=5)"

# Default command: run migrations then start server with gunicorn
# Using 2 workers for 1GB RAM instance (reduced from 3 to prevent OOM)
# 2 threads per worker for concurrency (4 total concurrent requests)
# Reduced timeout to 60s to fail faster and prevent memory buildup
# max-requests recycles workers to prevent memory leaks
# access-logformat: %(L)s = response time in decimal seconds (for slow-request analysis)
CMD ["sh", "-c", "python3 manage.py migrate --noinput && gunicorn --workers 2 --threads 2 --bind 0.0.0.0:8000 --timeout 60 --max-requests 500 --max-requests-jitter 50 --access-logformat '%(h)s %(l)s %(u)s %(t)s \"%(r)s\" %(s)s %(b)s %(L)s' django_config.wsgi:application"]

