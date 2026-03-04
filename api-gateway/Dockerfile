# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY api-gateway/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

# Create non-root user
RUN groupadd -r tracerat && useradd -r -g tracerat -d /app -s /sbin/nologin tracerat

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy shared libraries
COPY shared/ /app/shared/

# Copy api-gateway application
COPY api-gateway/app/ /app/app/

# Set ownership
RUN chown -R tracerat:tracerat /app

USER tracerat

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
