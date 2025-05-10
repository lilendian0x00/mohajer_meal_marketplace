# Dockerfile

# --- Stage 1: Build Stage ---
# Use an official Python 3.12 runtime as a parent image
FROM python:3.12-slim as builder

# Set the working directory in the container
WORKDIR /app

# Install build dependencies (if any, e.g., for packages that compile C extensions)
# Example for psycopg2 (if you use PostgreSQL and need compilation):
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     libpq-dev \
#  && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install Python dependencies
# --no-cache-dir: Disables the pip cache to reduce image size
# --prefix=/install: Installs packages into a specific directory for easier copying later
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Final Stage ---
# Use a slim Python 3.12 image for the final application
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy only the installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy the rest of your application code
# Adjust these COPY commands based on your exact project structure
COPY main.py .
COPY bot.py .
COPY config.py .
COPY background_tasks.py .
COPY utility.py .
COPY handlers /app/handlers
COPY self_market /app/self_market

# Expose any port if your application listens on one (not typical for a polling Telegram bot)
# EXPOSE 8080

# ENVS
ENV TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_HERE_RUNTIME"
ENV DATABASE_URL="sqlite+aiosqlite:///data/self_market.db"
ENV ADMIN_TELEGRAM_IDS=""
ENV LOG_LEVEL="INFO"
ENV PENDING_TIMEOUT_MINUTES="5"
ENV LISTING_TIMEOUT_CHECK_INTERVAL_MINUTES="5"
ENV MEALS_UPDATE_CHECK_INTERVAL_MINUTES="720"

# Command to run your application
# Ensure your main.py is executable or called via python
CMD ["python", "main.py"]

# TODO: Create a non-root user to run the application for better security
# RUN groupadd -r myuser && useradd --no-log-init -r -g myuser myuser
# USER myuser