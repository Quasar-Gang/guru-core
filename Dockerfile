# One image, every role. The entrypoint decides which: api_server, api_worker,
# engine_worker, catalog_server, seed_role_models, check_llm.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so a source change does not invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["python", "-m"]
CMD ["cmd.api_server"]
