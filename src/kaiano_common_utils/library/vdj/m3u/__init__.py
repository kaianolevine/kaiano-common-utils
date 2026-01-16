"""VirtualDJ .m3u history processing (local-only parsing + optional Drive helpers).

Recommended entry point:
- M3UToolbox

Backwards compatible functions are also exported for existing callers.
"""

from .api import M3UEntry, M3UToolbox
from .legacy import (
    download_m3u_file,
    extract_tag_value,
    get_all_m3u_files,
    get_most_recent_m3u_file,
    parse_m3u,
    parse_m3u_lines,
    parse_time_str,
)

__all__ = [
    "M3UToolbox",
    "M3UEntry",
    "parse_time_str",
    "extract_tag_value",
    "get_most_recent_m3u_file",
    "get_all_m3u_files",
    "download_m3u_file",
    "parse_m3u_lines",
    "parse_m3u",
]
