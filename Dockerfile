# Deployment only. Framework milestone does NOT build this image locally (U-6).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY configs ./configs

RUN uv sync --frozen --no-dev --no-editable && chown -R 10001:10001 /app

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

# Bind inside the container; host exposure is controlled by compose ports (127.0.0.1 by default).
CMD ["uvicorn", "cueloom.server:app", "--host", "0.0.0.0", "--port", "8000"]
