FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" django
COPY app/pyproject.toml app/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ .
COPY cmd/django_entrypoint.sh /usr/local/bin/django_entrypoint.sh
RUN mkdir -p staticfiles && chown django staticfiles

USER django
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["sh", "/usr/local/bin/django_entrypoint.sh"]
