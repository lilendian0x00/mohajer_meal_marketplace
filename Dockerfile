# Dockerfile

# Build Stage
FROM python:3.12-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final Stage
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local

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

CMD ["python", "main.py"]