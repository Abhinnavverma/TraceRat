FROM python:3.12-slim AS builder

WORKDIR /build

COPY vectorization-service/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    --timeout=300 --retries=5 \
    -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

RUN groupadd -r tracerat && useradd -r -g tracerat tracerat

COPY --from=builder /install /usr/local

WORKDIR /app

COPY shared/ /app/shared/
COPY vectorization-service/app/ /app/app/

USER tracerat

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]