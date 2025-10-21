import datetime
import logging

from kaiano_common_utils import config

default_level = config.LOGGING_LEVEL

logging.basicConfig(
    level=getattr(logging, default_level, logging.DEBUG),
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
    level_to_set = default_level
    normalized_level = level_to_set.upper()
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if normalized_level in valid_levels:
        logger.setLevel(getattr(logging, normalized_level))
        logging.getLogger().info(f"Logger level set to: {normalized_level}")
    else:
        logging.getLogger().warning(
            f"Invalid logging level: {level_to_set}. Level not changed."
        )
        logging.getLogger().warning(f"config.LOGGING_LEVEL: {config.LOGGING_LEVEL}.")
        logging.getLogger().warning(f"default_level: {default_level}.")
    return logger


def format_date(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def set_logging_level(level: str):
    normalized_level = level.upper()
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if normalized_level not in valid_levels:
        logging.getLogger().warning(
            f"Invalid logging level: {level}. Level not changed."
        )
        return
    new_level = getattr(logging, normalized_level)
    logging.getLogger().setLevel(new_level)
    logger.setLevel(new_level)
    logging.getLogger().info(f"Logging level changed to: {normalized_level}")
