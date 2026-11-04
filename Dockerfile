# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA org.opencontainers.image.title=polybot
ENV POLYBOT_GIT_SHA=$GIT_SHA
RUN useradd --system --uid 10001 --home /app polybot
COPY --from=deps /opt/venv /opt/venv
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY tests/fixtures ./tests/fixtures
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev && chown -R polybot /app
USER polybot
EXPOSE 9108
HEALTHCHECK --interval=30s --timeout=12s --start-period=20s --retries=3 CMD ["polybot", "healthcheck"]
ENTRYPOINT ["polybot"]
CMD ["--help"]
