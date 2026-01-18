import datetime
import logging

import kaiano_common_utils.config as config
from dotenv import load_dotenv

load_dotenv()

default_level = config.LOGGING_LEVEL
logging.basicConfig(
    level=default_level,
    format="%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d - %(funcName)s] %(message)s",
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
