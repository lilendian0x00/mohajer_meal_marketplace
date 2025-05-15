#!/bin/sh
set -e # Exit immediately if a command exits with a non-zero status.

# Run Alembic migrations
# Make sure your project's virtual environment is active if alembic is installed there,
# or that alembic is on the PATH.
# If using `uv run`, you can prefix alembic command with `uv run`.
echo "Running database migrations..."
uv run alembic upgrade head # Or just `alembic upgrade head` if alembic is on PATH

# Start the main application (your current CMD)
echo "Starting application..."
exec "$@" # Executes the command passed to the script (which will be your CMD from Dockerfile)

