# syntax=docker/dockerfile:1

# mem-mesh Docker Image
# Multi-stage build for optimized production image

# Stage 1: Builder
FROM python:3.13-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /build

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install torch CPU first (largest dependency, separate layer for cache)
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu

# Copy dependency files and install remaining dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Note: Embedding model is NOT pre-downloaded.
# Users select their preferred model via the onboarding page on first run.
# Use docker-compose volume mount to persist the HuggingFace cache across restarts.

# Stage 2: Runtime
FROM python:3.13-slim

LABEL org.opencontainers.image.title="mem-mesh" \
      org.opencontainers.image.description="AI Memory Management MCP Server" \
      org.opencontainers.image.source="https://github.com/JINWOO-J/mem-mesh"

# Python runtime settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash memmesh

# Set working directory
WORKDIR /app

# Create data and HuggingFace cache directories
RUN mkdir -p /app/data /home/memmesh/.cache/huggingface && \
    chown -R memmesh:memmesh /app/data /home/memmesh/.cache

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=memmesh:memmesh . .

# Switch to non-root user
USER memmesh

# Expose ports
# 8000: Web Dashboard + REST API
# 8001: MCP SSE endpoint
EXPOSE 8000 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: Run web server
CMD ["python", "-m", "app.web"]
