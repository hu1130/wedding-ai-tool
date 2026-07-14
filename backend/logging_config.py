"""Logging setup for queue workers and container runtime output."""
import logging
import sys

from backend.config import settings


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging() -> None:
    """Configure stdout logging without clobbering an existing server setup."""
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    third_party_level = level if level <= logging.DEBUG else logging.WARNING
    logging.getLogger("httpx").setLevel(third_party_level)
    logging.getLogger("httpcore").setLevel(third_party_level)

    if root_logger.handlers:
        root_logger.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stdout,
    )
