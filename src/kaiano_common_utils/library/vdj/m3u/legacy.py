"""Backwards-compatible function wrappers."""

from __future__ import annotations

from .api import DriveFacade, ParseFacade


def parse_time_str(time_str):
    return ParseFacade.parse_time_str(time_str)


def extract_tag_value(line, tag):
    return ParseFacade.extract_tag_value(line, tag)


def get_most_recent_m3u_file(drive_service):
    return DriveFacade(drive_service).get_most_recent_m3u_file()


def get_all_m3u_files(drive_service):
    return DriveFacade(drive_service).get_all_m3u_files()


def download_m3u_file(drive_service, file_id):
    return DriveFacade(drive_service).download_m3u_file(file_id)


def parse_m3u_lines(lines, existing_keys, file_date_str):
    return ParseFacade.parse_m3u_lines(lines, existing_keys, file_date_str)


def parse_m3u(sheets_service, filepath, spreadsheet_id):
    return ParseFacade.parse_m3u(sheets_service, filepath, spreadsheet_id)
