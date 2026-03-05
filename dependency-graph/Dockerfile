# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY dependency-graph/requirements.txt .
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

# Copy dependency-graph application
COPY dependency-graph/app/ /app/app/

# Set ownership
RUN chown -R tracerat:tracerat /app

USER tracerat

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
