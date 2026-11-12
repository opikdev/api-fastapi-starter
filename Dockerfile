FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS runtime
# Take Debian's security fixes that are newer than the base image. The app never installs
# packages at runtime, so drop pip and the copy ensurepip bundles.
RUN apt-get update \
  && apt-get upgrade --yes \
  && rm -rf /var/lib/apt/lists/* /usr/local/bin/pip* /usr/local/lib/python3.15/site-packages/pip* \
    /usr/local/lib/python3.15/ensurepip \
  && useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=3000
USER app
EXPOSE 3000
# Standard library only, so a check costs milliseconds even on a throttled CPU.
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
  CMD ["python", "-m", "app.healthcheck"]
ENTRYPOINT ["api-fastapi-starter"]
CMD ["serve"]
