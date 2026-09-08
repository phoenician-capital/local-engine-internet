FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        wget \
        gnupg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY engine ./engine

EXPOSE 8090

CMD ["uvicorn", "engine.main:app", "--host", "0.0.0.0", "--port", "8090"]
