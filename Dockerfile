FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc python3-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY . .

# Render Web Service: слушаем 0.0.0.0 и порт из $PORT
CMD ["sh", "-c", "uvicorn admin_panel:app --host 0.0.0.0 --port ${PORT:-8000}"]
