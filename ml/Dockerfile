# The ML service. The model itself runs in Ollama on the host (GPU), not in this container.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY maestro ./maestro
COPY data ./data
RUN pip install --no-cache-dir .

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4)"
CMD ["maestro", "serve", "--host", "0.0.0.0", "--port", "8001"]
