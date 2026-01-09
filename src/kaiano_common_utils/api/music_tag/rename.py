import os
import re
from typing import Dict, List, Optional

import kaiano_common_utils.logger as log

from .retagger_music_tag import get_metadata


def new_sanitize_filename(value: str) -> str:
    # Replace any non-alphanumeric or underscore character with underscore
    value = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    return value


def sanitize_filename(value: str) -> str:
    value = re.sub(r"\s+", "_", value)
    return re.sub(r"[^a-zA-Z0-9_\-]", "", value)


# Helper to avoid filename collisions
def _unique_path(base_path: str) -> str:
    """
    Ensure the returned path does not collide with an existing file by appending
    an incrementing suffix before the extension, e.g. "name.mp3" -> "name_1.mp3".
    """
    directory, filename = os.path.dirname(base_path), os.path.basename(base_path)
    stem, ext = os.path.splitext(filename)
    candidate = base_path
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}_{counter}{ext}")
        counter += 1
    return candidate


def rename_music_file(file_path: str, output_dir: str, separator: str) -> str:
    """
    Rename a single file based on extracted metadata. Returns the destination path.

    Args:
        file_path: Source file to rename.
        output_dir: Target directory to place the renamed file.
        separator: Token to join filename parts.
        extension: Optional extension override (e.g., ".mp3"). If None, preserve original.
        dry_run: If True, do not actually rename/move files; return the intended path.
    """
    metadata = get_metadata(file_path)
    filename_parts = [
        metadata.get("bpm", ""),
        metadata.get("title", ""),
        metadata.get("artist", ""),
        metadata.get("comment", ""),
    ]
    cleaned_parts = [sanitize_filename(p) for p in filename_parts if p]
    final_ext = os.path.splitext(file_path)[1]
    proposed_name = f"{separator.join(cleaned_parts)}{final_ext}"
    proposed_path = os.path.join(output_dir, proposed_name)
    dest_path = _unique_path(proposed_path)

    log.debug(f"Renaming {file_path} -> {dest_path}")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    os.rename(file_path, dest_path)
    return dest_path


def rename_files_in_directory(directory: str, config: Dict) -> Dict[str, int]:
    """
    Scan a directory recursively, renaming files according to config.

    Returns a summary dict: {"processed": int, "renamed": int, "skipped": int, "failed": int}
    """
    log.info(f"Scanning directory: {directory}")
    summary = {"processed": 0, "renamed": 0, "skipped": 0, "failed": 0}
    for root, _, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            if not os.path.isfile(full_path):
                continue
            summary["processed"] += 1
            try:
                metadata = get_metadata(full_path)
                new_name = generate_filename(metadata, config)
                if not new_name:
                    log.warning(f"Skipping file due to missing metadata: {file}")
                    summary["skipped"] += 1
                    continue
                new_path = os.path.join(root, new_name)
                new_path = _unique_path(new_path)
                if os.path.abspath(new_path) == os.path.abspath(full_path):
                    log.debug(f"Name unchanged for: {file}")
                    summary["skipped"] += 1
                    continue
                log.debug(f"Renaming file: {file} -> {os.path.basename(new_path)}")
                os.rename(full_path, new_path)
                summary["renamed"] += 1
                log.info(f"Renamed: {file} -> {os.path.basename(new_path)}")
            except ValueError as e:
                log.warning(f"Metadata parsing failed for {file}: {e}")
                summary["failed"] += 1
            except OSError as e:
                log.error(f"Filesystem error for {file}: {e}")
                summary["failed"] += 1
            except Exception:
                log.error(f"Failed to rename file: {file}", exc_info=True)
                summary["failed"] += 1
    log.info(f"Summary: {summary}")
    return summary


def generate_filename(metadata: Dict[str, str], config: Dict) -> Optional[str]:
    """
    Generate a sanitized filename based on selected metadata fields and config-defined order.

    Config keys used:
      - rename_order: List[str] of field names in order
      - required_fields: List[str] of fields that must be present/non-empty
      - extension: default extension (e.g., ".mp3")
      - separator: string between parts (default "__")
    """
    log.debug(f"Generating filename using metadata: {metadata} and config: {config}")
    rename_order: List[str] = config.get("rename_order", [])
    required_fields: List[str] = config.get("required_fields", [])
    extension: str = config.get("extension", ".mp3")
    separator: str = config.get("separator", "__")

    filename_parts: List[str] = []
    for field in rename_order:
        value = metadata.get(field, "")
        log.debug(f"Field: {field}, Value: {value}")
        if not value and field in required_fields:
            log.debug(
                f"Required field '{field}' is missing, skipping filename generation."
            )
            return None
        sanitized = sanitize_filename(value)
        if sanitized:
            filename_parts.append(sanitized)

    if not filename_parts:
        log.debug("No valid fields found for filename generation, returning None.")
        return None

    filename = f"{separator.join(filename_parts)}{extension}"
    log.debug(f"Generated filename: {filename}")
    return filename
