import datetime
import logging

from kaiano_common_utils import config

level_name = config.LOGGING_LEVEL
if level_name not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
    level_name = "DEBUG"

logging.basicConfig(
    level=getattr(logging, level_name, logging.INFO),
    format="%(asctime)s [%(levelname)s] [%(name)s.%(funcName)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logging.getLogger().info(f"Logger initialized with level: {level_name}")

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
