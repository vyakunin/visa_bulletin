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

WORKDIR /app

# Copy project files
COPY . .

# Build with Bazel (creates hermetic build)
RUN bazel build //:runserver //:refresh_data //:refresh_data_incremental //:migrate

# Extract built artifacts
RUN mkdir -p /app/dist && \
    cp -r bazel-bin/* /app/dist/ && \
    cp -r lib /app/dist/ && \
    cp -r models /app/dist/ && \
    cp -r extractors /app/dist/ && \
    cp -r webapp /app/dist/ && \
    cp -r django_config /app/dist/ && \
    cp manage.py /app/dist/

# Production stage
FROM python:3.11-slim

# Security: Run as non-root user
RUN groupadd -r visabulletin && useradd -r -g visabulletin visabulletin

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built artifacts from builder
COPY --from=bazel-builder /app/dist /app
COPY --from=bazel-builder /app/.bazelversion /app/
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p saved_pages logs static && \
    chown -R visabulletin:visabulletin /app

# Switch to non-root user
USER visabulletin

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000').read()" || exit 1

# Default command: run migrations then start server with gunicorn
# Using 3 workers (2 * CPU + 1), 2 threads per worker for concurrency
# max-requests recycles workers to prevent memory leaks
CMD ["sh", "-c", "python3 manage.py migrate --noinput && gunicorn --workers 3 --threads 2 --bind 0.0.0.0:8000 --timeout 120 --max-requests 1000 --max-requests-jitter 50 django_config.wsgi:application"]

