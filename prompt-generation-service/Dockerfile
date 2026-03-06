# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app

COPY prompt-generation-service/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy shared library
COPY shared/ /app/shared/

# Copy application code
COPY prompt-generation-service/app/ /app/app/

# Create non-root user
RUN useradd --create-home tracerat
USER tracerat

EXPOSE 8005

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
