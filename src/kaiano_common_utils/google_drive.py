import io
import os
from typing import Dict, List

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import kaiano_common_utils._google_credentials as google_api
import kaiano_common_utils.google_sheets as google_sheets
from kaiano_common_utils import logger as log

log = log.get_logger()
FOLDER_CACHE = {}


def get_drive_service():
    return google_api.get_drive_client()


def extract_date_from_filename(filename):
    import re

    match = re.match(r"(\d{4}-\d{2}-\d{2})", filename)
    return match.group(1) if match else filename


def list_files_in_folder(
    service,
    folder_id,
    mime_type_filter=None,
    include_all_drives=True,
    include_folders=False,
):
    """
    List files in a Google Drive folder, optionally filtering by MIME type.
    Supports both standard Drive and Shared Drive contexts.
    """
    log.debug(
        f"list_files_in_folder called with folder_id={folder_id}, mime_type_filter={mime_type_filter}, include_all_drives={include_all_drives}, include_folders={include_folders}"
    )
    query = f"'{folder_id}' in parents"
    if not include_folders:
        query += " and mimeType != 'application/vnd.google-apps.folder'"
    if mime_type_filter:
        query += f" and mimeType = '{mime_type_filter}'"
        log.info(f"Applying MIME type filter: {mime_type_filter}")
    query += " and trashed = false"
    log.debug(f"Drive query: {query}")

    files = []
    page_token = None
    while True:
        try:
            params = {
                "q": query,
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)",
                "pageToken": page_token,
                "orderBy": "modifiedTime desc",
            }
            if include_all_drives:
                params["supportsAllDrives"] = True
                params["includeItemsFromAllDrives"] = True
                params["spaces"] = "drive"

            result = service.files().list(**params).execute()
            batch = result.get("files", [])
            files.extend(batch)
            page_token = result.get("nextPageToken", None)
            log.debug(
                f"Fetched {len(batch)} files (total: {len(files)}) from folder {folder_id}"
            )
            if page_token is None:
                break
        except Exception as e:
            log.error(f"❌ Error listing files in folder {folder_id}: {e}")
            break

    if not files:
        log.warning(f"No files found in folder {folder_id}.")
    else:
        log.info(f"📂 Found {len(files)} files in folder {folder_id}.")
        log.debug(", ".join([f"{f.get('id')}:{f.get('name')}" for f in files]))

    return files


def list_music_files(service, folder_id):
    log.debug(f"Listing audio files in folder {folder_id}")
    query = f"'{folder_id}' in parents and mimeType contains 'audio'"
    results = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = results.get("files", [])
    if not files:
        log.warning(f"No audio files found in folder {folder_id}")
    else:
        log.info(f"🎵 Found {len(files)} audio files in folder {folder_id}")
    return files


def get_or_create_folder(parent_folder_id: str, name: str, drive_service) -> str:
    """Returns the folder ID for a subfolder under parent_folder_id with the given name.
    Creates it if it doesn't exist, using an in-memory cache to avoid duplication."""
    cache_key = f"{parent_folder_id}/{name}"
    if cache_key in FOLDER_CACHE:
        log.debug(f"Cache hit for folder {name} under {parent_folder_id}")
        return FOLDER_CACHE[cache_key]

    try:
        query = (
            f"'{parent_folder_id}' in parents and "
            f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        response = (
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        folders = response.get("files", [])
        if folders:
            log.info(
                f"📁 Found existing folder '{name}' under parent {parent_folder_id}"
            )
            folder_id = folders[0]["id"]
        else:
            log.info(f"📁 Creating new folder '{name}' under parent {parent_folder_id}")
            folder_metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_folder_id],
            }
            folder = (
                drive_service.files()
                .create(body=folder_metadata, fields="id", supportsAllDrives=True)
                .execute()
            )
            folder_id = folder["id"]
        FOLDER_CACHE[cache_key] = folder_id
        return folder_id
    except HttpError as e:
        log.error(f"❌ Drive API error creating/finding folder '{name}': {e}")
        raise


def get_all_subfolders(drive_service, parent_folder_id: str) -> List[Dict]:
    """Returns all subfolders in a given parent folder."""
    log.info(f"📂 Retrieving subfolders in folder {parent_folder_id}")
    try:
        query = f"'{parent_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = []
        page_token = None
        while True:
            response = (
                drive_service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            batch = response.get("files", [])
            folders.extend(batch)
            page_token = response.get("nextPageToken", None)
            if page_token is None:
                break
        if folders:
            log.info(f"📁 Found {len(folders)} subfolders under {parent_folder_id}")
        else:
            log.warning(f"No subfolders found under {parent_folder_id}")
        return folders
    except HttpError as e:
        log.error(f"❌ Error retrieving subfolders: {e}")
        raise


def download_file(service, file_id, destination_path):
    """Download a file from Google Drive by ID using the Drive API."""
    log.info(f"⬇️ Starting download for file {file_id} → {destination_path}")
    try:
        fh = io.FileIO(destination_path, "wb")
        log.debug(f"Opened file handle for {destination_path}")
    except Exception as e:
        log.error(f"❌ Failed to open destination file: {e}")
        raise

    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    chunk_count = 0
    while not done:
        status, done = downloader.next_chunk()
        chunk_count += 1
        progress_percent = int(status.progress() * 100) if status else 0
        log.info(f"⬇️ Download progress: {progress_percent}%")
    log.info(f"✅ Download complete for file {file_id}")
    log.debug(f"Total chunks downloaded: {chunk_count}")


def upload_to_drive(drive, filepath, parent_id):
    """Uploads a CSV as a Google Sheet to a specified Drive folder."""
    log.info(f"📤 Uploading '{filepath}' to Drive folder '{parent_id}'")
    try:
        file_metadata = {
            "name": os.path.basename(filepath),
            "parents": [parent_id],
            "mimeType": "application/vnd.google-apps.spreadsheet",
        }
        media = MediaFileUpload(filepath, mimetype="text/csv")
        uploaded = (
            drive.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        log.info(f"📄 Uploaded to Drive as Google Sheet: {filepath}")
        log.debug(f"Uploaded file ID: {uploaded['id']}")

        gc = google_sheets.get_gspread_client()
        spreadsheet = gc.open_by_key(uploaded["id"])
        for sheet in spreadsheet.worksheets():
            first_row = sheet.row_values(1)
            if first_row and first_row[0].strip().lower().startswith("sep="):
                sheet.delete_rows(1)
        return uploaded["id"]
    except Exception as e:
        log.error(f"❌ Upload failed for '{filepath}': {e}")
        raise


def create_spreadsheet(
    drive_service,
    name,
    parent_folder_id,
    mime_type: str = "application/vnd.google-apps.spreadsheet",
):
    """Finds or creates a spreadsheet by name."""
    log.info(f"🔍 Searching for file '{name}' in folder {parent_folder_id}")
    try:
        query = f"'{parent_folder_id}' in parents and name = '{name}' and mimeType = '{mime_type}' and trashed = false"
        response = (
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = response.get("files", [])
        if files:
            log.info(f"📄 Found existing file '{name}' (ID: {files[0]['id']})")
            return files[0]["id"]
        log.info(f"➕ No existing file found, creating new: '{name}'")
        file_metadata = {
            "name": name,
            "mimeType": mime_type,
            "parents": [parent_folder_id],
        }
        new_file = (
            drive_service.files()
            .create(body=file_metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        log.info(f"🆕 Created new file '{name}' (ID: {new_file['id']})")
        return new_file["id"]
    except HttpError as e:
        log.error(f"❌ Error finding/creating spreadsheet '{name}': {e}")
        raise


def move_file_to_folder(drive_service, file_id, folder_id):
    """
    Moves a file to a specified folder.
    """
    try:
        # Get current parents
        file = drive_service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []))
        log.debug(f"Previous parents for file {file_id}: {previous_parents}")
        # Move the file to the new folder
        drive_service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()
        log.info(f"Moved file {file_id} to folder {folder_id}")
    except Exception as e:
        log.error(f"❌ Error moving file {file_id} to folder {folder_id}: {e}")
        raise


def remove_file_from_root(drive_service, file_id):
    """
    Removes a file from the root folder.
    """
    try:
        file = drive_service.files().get(fileId=file_id, fields="parents").execute()
        parents = file.get("parents", [])
        if "root" in parents:
            drive_service.files().update(
                fileId=file_id, removeParents="root", fields="id, parents"
            ).execute()
            log.info(f"Removed file {file_id} from root folder")
        else:
            log.warning(
                f"File {file_id} is not in the root folder, cannot remove from root"
            )
    except Exception as e:
        log.error(f"❌ Error removing file {file_id} from root: {e}")
        raise


def find_or_create_file_by_name(
    drive_service,
    name: str,
    parent_folder_id: str,
    mime_type: str = "application/vnd.google-apps.spreadsheet",
) -> str:
    """
    Finds a file by name in the specified folder. If not found, creates a new file with that name.
    This function supports Shared Drives (supportsAllDrives=True).
    Returns the file ID.
    """
    log.info(
        f"🔍 Searching for file '{name}' in folder ID {parent_folder_id} (shared drives enabled)"
    )
    try:
        query = f"'{parent_folder_id}' in parents and name = '{name}' and mimeType = '{mime_type}' and trashed = false"
        response = (
            drive_service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = response.get("files", [])
        if files:
            log.info(f"📄 Found existing file '{name}' with ID {files[0]['id']}")
            return files[0]["id"]
        else:
            log.info(
                f"➕ No existing file named '{name}' — creating new one in parent {parent_folder_id}"
            )
            file_metadata = {
                "name": name,
                "mimeType": mime_type,
                "parents": [parent_folder_id],
            }
            file = (
                drive_service.files()
                .create(body=file_metadata, fields="id", supportsAllDrives=True)
                .execute()
            )
            log.info(f"🆕 Created new file '{name}' with ID {file['id']}")
            return file["id"]
    except HttpError as error:
        log.error(f"An error occurred while finding or creating file: {error}")
        raise


def find_subfolder_id(
    service, parent_folder_id: str, subfolder_name: str
) -> str | None:
    """
    Finds the ID of a subfolder with the given name inside the specified parent folder.

    Args:
        service: An authorized Google Drive service instance.
        parent_folder_id (str): The ID of the parent folder to search within.
        subfolder_name (str): The exact name of the subfolder to find.

    Returns:
        str | None: The ID of the subfolder if found, otherwise None.
    """
    log.debug(
        f"Searching for subfolder '{subfolder_name}' under parent '{parent_folder_id}'"
    )
    try:
        query = (
            f"'{parent_folder_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{subfolder_name}' and trashed = false"
        )
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=10,
            )
            .execute()
        )
        files = response.get("files", [])
        if files:
            log.info(
                f"Found subfolder '{subfolder_name}' with ID {files[0]['id']} under parent '{parent_folder_id}'"
            )
            return files[0]["id"]
        else:
            log.warning(
                f"No subfolder named '{subfolder_name}' found under parent '{parent_folder_id}'"
            )
    except Exception as e:
        log.error(
            f"❌ Error finding subfolder '{subfolder_name}' under parent '{parent_folder_id}': {e}"
        )
    return None
