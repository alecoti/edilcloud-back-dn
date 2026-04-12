FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY demo-assets /app/demo-assets
COPY docs /app/docs
COPY src /app/src
COPY scripts /app/scripts
COPY manage.py /app/manage.py

RUN mkdir -p /app/media /app/staticfiles

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install -e .

EXPOSE 8001

CMD ["gunicorn", "edilcloud.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8001", "--workers", "3", "--timeout", "120"]
