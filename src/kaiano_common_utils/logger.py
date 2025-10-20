import datetime
import logging
import os

level_name = os.getenv("LOG_LEVEL", "ERROR").upper()

logging.basicConfig(
    level=getattr(logging, level_name, logging.ERROR),
    format="%(asctime)s [%(levelname)s] [%(name)s.%(funcName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("core")

# Shortcut aliases
debug = logger.debug
info = logger.info
warning = logger.warning
error = logger.error
exception = logger.exception


def get_logger():
    return logger


def format_date(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")
