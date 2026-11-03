FROM python:3.14-slim AS builder

WORKDIR /build

# Necessário apenas quando alguma dependência não oferece wheel para a plataforma.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system kookie && useradd --system --gid kookie --home-dir /app kookie

COPY --from=builder /install /usr/local
COPY src ./src

USER kookie:kookie

CMD ["python", "-m", "src"]
