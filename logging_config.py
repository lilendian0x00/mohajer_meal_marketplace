import logging
import sys
from pythonjsonlogger import json
import config


def setup_logging():
    """Configures logging for the application.
    Outputs JSON to stdout in 'production' mode, plain text otherwise.
    """
    root_logger = logging.getLogger()

    log_level_str = config.LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    root_logger.setLevel(log_level)

    # Remove any existing handlers from the root logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    log_handler = logging.StreamHandler(sys.stdout)

    if config.BOT_MODE == "production":  # Or a specific env var like LOG_FORMAT_JSON="true"
        formatter = json.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(message)s %(exc_info)s %(stack_info)s",
            rename_fields={
                "levelname": "level",
                "asctime": "time",
                "name": "logger_name"
            },
            datefmt="%Y-%m-%dT%H:%M:%S.%3fZ"
        )
        log_handler.setFormatter(formatter)
        # Initial log message (will also be JSON)
        logging.info("JSON logging to stdout configured (for Loki/centralized logging).")
    else:  # For "dev" or other non-production modes
        formatter = logging.Formatter(config.LOG_FORMAT)  # Your existing plain text format
        log_handler.setFormatter(formatter)
        logging.info(f"Plain text logging to stdout configured for '{config.BOT_MODE}' mode.")

    root_logger.addHandler(log_handler)

    # Configure logging levels for potentially noisy third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.INFO)  # PTB can be verbose on DEBUG
    logging.getLogger("telegram.bot").setLevel(logging.INFO)
    logging.getLogger("telegram.request").setLevel(logging.INFO)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
