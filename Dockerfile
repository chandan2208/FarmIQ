FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
COPY app ./app
COPY web ./web
RUN mkdir -p data/cache data/uploads
ENV FARMIQ_ENV=production PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT} --timeout 120"]
