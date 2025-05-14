FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# ENVS
ENV TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_HERE_RUNTIME"
ENV DATABASE_URL="sqlite+aiosqlite:///data/self_market.db"
ENV BOT_PERSISTENCE_FILEPATH="/data/bot_persistence"
ENV SAMAD_PROXY="socks5://dornSyHxu6:LMSmlI5vMo@laser.kafsabtaheri.com:13865"
ENV ADMIN_TELEGRAM_IDS=""
ENV LOG_LEVEL="INFO"
ENV PENDING_TIMEOUT_MINUTES="5"
ENV LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES="5"
ENV MEALS_UPDATE_CHECK_INTERVAL_MINUTES="720"
ENV SAMAD_API_USERNAME="YOUR_SAMAD_USERNAME_RUNTIME"
ENV SAMAD_API_PASSWORD="YOUR_SAMAD_PASSWORD_RUNTIME"

CMD ["uv","run", "main.py"]