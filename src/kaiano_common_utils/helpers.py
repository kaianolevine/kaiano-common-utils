import re
import unicodedata
from typing import Any, Tuple

from kaiano_common_utils import config
from kaiano_common_utils import logger as log

log = log.get_logger()


def levenshtein_distance(a, b):
    """Compute Levenshtein edit distance between two strings."""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[m][n]


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


def normalize_prefixes_in_source(drive):
    """Remove leading status prefixes from files in the CSV source folder.
    If a file name starts with 'FAILED_' or 'possible_duplicate_' (case-insensitive),
    this function will attempt to rename it to the original base name (i.e. strip the prefix).
    Uses supportsAllDrives=True to operate on shared drives.
    """
    FAILED_PREFIX = "FAILED_"
    POSSIBLE_DUPLICATE_PREFIX = "possible_duplicate_"
    COPY_OF_PREFIX = "Copy of "
    try:
        log.debug("normalize_prefixes_in_source: listing source folder files")
        resp = (
            drive.files()
            .list(
                q=f"'{config.CSV_SOURCE_FOLDER_ID}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = resp.get("files", [])
        log.debug(f"normalize_prefixes_in_source: found {len(files)} files to inspect")

        for f in files:
            original_name = f.get("name", "")
            lower = original_name.lower()
            prefix = None
            if lower.startswith(FAILED_PREFIX.lower()):
                prefix = original_name[: len(FAILED_PREFIX)]
            elif lower.startswith(POSSIBLE_DUPLICATE_PREFIX.lower()):
                prefix = original_name[: len(POSSIBLE_DUPLICATE_PREFIX)]
            elif lower.startswith(COPY_OF_PREFIX.lower()):
                prefix = original_name[: len(COPY_OF_PREFIX)]

            if prefix:
                new_name = original_name[len(prefix) :]
                # If new_name is empty or already exists, skip
                if not new_name:
                    log.warning(
                        f"normalize_prefixes_in_source: derived empty new name for {original_name}, skipping"
                    )
                    continue

                # Check if a file with target name already exists in the same folder
                try:
                    query = f"name = '{new_name}' and '{config.CSV_SOURCE_FOLDER_ID}' in parents and trashed = false"
                    exists_resp = (
                        drive.files()
                        .list(
                            q=query,
                            fields="files(id, name)",
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        )
                        .execute()
                    )
                    if exists_resp.get("files"):
                        log.debug(
                            f"normalize_prefixes_in_source: target name '{new_name}' already exists in source folder — leaving '{original_name}' as-is"
                        )
                        continue
                except Exception as e:
                    log.debug(
                        f"normalize_prefixes_in_source: error checking existing file for {new_name}: {e}"
                    )

                try:
                    log.debug(
                        f"normalize_prefixes_in_source: renaming '{original_name}' -> '{new_name}'"
                    )
                    drive.files().update(
                        fileId=f["id"], body={"name": new_name}, supportsAllDrives=True
                    ).execute()
                except Exception as e:
                    log.error(
                        f"normalize_prefixes_in_source: failed to rename {original_name}: {e}"
                    )
    except Exception as e:
        log.error(f"normalize_prefixes_in_source: unexpected error: {e}")


def _safe_str(v: Any) -> str:
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


def title_case_words(v: Any) -> str:
    """
    Capitalize every word that starts with a letter.
    Preserves existing punctuation and spacing.
    """
    s = _safe_str(v)
    if not s:
        return ""

    def repl(match: re.Match) -> str:
        word = match.group(0)
        return word[0].upper() + word[1:]

    # Capitalize words that start with an alphabetic character
    return re.sub(r"\b[a-zA-Z][^\s]*", repl, s)


def normalize_for_compare(v: Any) -> str:
    """Canonical comparison: None / 'None' / whitespace all become empty string."""
    return _safe_str(v).strip()


def normalize_year_for_tag(v: Any) -> str:
    s = _safe_str(v).strip()
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
    s = _safe_str(v)

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
