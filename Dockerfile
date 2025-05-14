# Dockerfile

# Build Stage
FROM python:3.12-slim as builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./

RUN uv pip install --target /install

# Final Stage
FROM python:3.12-slim
WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /install /usr/local/lib/python3.12/site-packages/

COPY main.py .
COPY bot.py .
COPY config.py .
COPY background_tasks.py .
COPY utility.py .
COPY handlers /app/handlers
COPY self_market /app/self_market

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

CMD ["python", "main.py"]