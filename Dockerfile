# python:3.12-slim, NOT Alpine. S6.
#
# Alpine uses musl rather than glibc, so numeric wheels do not match and pip
# compiles them from source instead. That turns a fast image build into a slow
# one and drags a toolchain into the image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not re-resolve them.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY reco ./reco

# Non-root. The service reads the application database read-only and writes only
# the ml_ prefix; the container should not hold privileges the service does not.
RUN useradd --create-home --uid 10001 reco
USER reco

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health').read()"

CMD ["uvicorn", "reco.main:app", "--host", "0.0.0.0", "--port", "8100"]
