import re
import unicodedata
from typing import Any, Tuple

from kaiano import logger as log

log = log.get_logger()


def extract_date_and_title(file_name: str) -> Tuple[str, str]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(.*)", file_name)
    if not match:
        return ("", file_name)
    date = match[1]
    title = match[2].lstrip("-_ ")
    return (date, title)


def extract_year_from_filename(filename):
    log.debug(f"extract_year_from_filename called with filename: {filename}")
    match = re.match(r"(\d{4})[-_]", filename)
    year = match.group(1) if match else None
    log.debug(f"Extracted year: {year} from filename: {filename}")
    return year


def normalize_csv(file_path):
    log.debug(f"normalize_csv called with file_path: {file_path} - reading file")
    with open(file_path, "r") as f:
        lines = f.readlines()
    cleaned_lines = [
        re.sub(r"\s+", " ", line).strip() for line in lines if line.strip()
    ]
    log.debug(f"Lines after cleaning: {len(cleaned_lines)}")
    with open(file_path, "w") as f:
        f.write("\n".join(cleaned_lines))
    log.debug(f"✅ Normalized: {file_path}")


def safe_str(v: Any) -> str:
    """Best-effort stringify without turning missing values into the literal 'None'."""
    if v is None:
        return ""
    try:
        s = str(v)
    except Exception:
        return ""
    # Some tag wrappers stringify missing values as "None"
    if s.strip().lower() == "none":
        return ""
    return s


def normalize_year_for_tag(v: Any) -> str:
    s = safe_str(v).strip()
    if not s:
        return ""
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return ""


def safe_filename_component(v: Any) -> str:
    """
    Normalize a value for safe, deterministic filenames.

    Rules:
    - Convert to string
    - Strip accents / diacritics
    - Lowercase
    - Remove all whitespace
    - Remove all non-alphanumeric characters (except underscore)
    - Collapse multiple underscores
    """
    s = safe_str(v)

    if not s:
        return ""

    # Normalize unicode (e.g. Beyoncé -> Beyonce)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))

    s = s.lower()

    # Remove whitespace entirely
    s = re.sub(r"\s+", "", s)

    # Replace any remaining invalid chars with underscore
    s = re.sub(r"[^a-z0-9_]", "_", s)

    # Collapse multiple underscores
    s = re.sub(r"_+", "_", s)

    return s.strip("_")
