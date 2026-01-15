import io
import os
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import kaiano_common_utils.google_sheets as google_sheets
from kaiano_common_utils import logger as log

from . import credentials as google_api
from ._retry import RetryConfig, execute_with_retry
from .types import DriveFile

log = log.get_logger()
FOLDER_CACHE = {}


class DriveFacade:
    """Small, stable wrapper around the Google Drive API.

    External code should generally access this through `GoogleAPI.drive`.
    """

    def __init__(self, service: Any, retry: RetryConfig | None = None):
        self._service = service
        self._retry = retry or RetryConfig()

    @property
    def service(self) -> Any:
        return self._service

    def list_files(
        self,
        parent_id: str,
        *,
        mime_type: Optional[str] = None,
        name_contains: Optional[str] = None,
        trashed: bool = False,
        include_folders: bool = True,
    ) -> list[DriveFile]:
        query = f"'{parent_id}' in parents"
        if not include_folders:
            query += " and mimeType != 'application/vnd.google-apps.folder'"
        if mime_type:
            query += f" and mimeType = '{mime_type}'"
        if name_contains:
            query += f" and name contains '{name_contains}'"
        query += f" and trashed = {str(trashed).lower()}"

        def _call(page_token: str | None):
            params = {
                "q": query,
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)",
                "pageToken": page_token,
                "orderBy": "modifiedTime desc",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
                "spaces": "drive",
            }
            return self._service.files().list(**params).execute()

        files: list[DriveFile] = []
        page_token: str | None = None
        while True:
            result = execute_with_retry(
                lambda: _call(page_token),
                context=f"listing files in folder {parent_id}",
                retry=self._retry,
            )
            for f in result.get("files", []):
                files.append(
                    DriveFile(
                        id=f.get("id", ""),
                        name=f.get("name", ""),
                        mime_type=f.get("mimeType"),
                        modified_time=f.get("modifiedTime"),
                    )
                )
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        return files

    def ensure_folder(self, parent_id: str, name: str) -> str:
        cache_key = f"{parent_id}/{name}"
        if cache_key in FOLDER_CACHE:
            return FOLDER_CACHE[cache_key]

        query = (
            f"'{parent_id}' in parents and name = '{name}' "
            "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )

        resp = execute_with_retry(
            lambda: self._service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute(),
            context=f"finding folder '{name}' under {parent_id}",
            retry=self._retry,
        )
        folders = resp.get("files", [])
        if folders:
            folder_id = folders[0]["id"]
        else:
            folder_metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            created = execute_with_retry(
                lambda: self._service.files()
                .create(
                    body=folder_metadata,
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute(),
                context=f"creating folder '{name}' under {parent_id}",
                retry=self._retry,
            )
            folder_id = created["id"]

        FOLDER_CACHE[cache_key] = folder_id
        return folder_id

    def copy_file(
        self, file_id: str, *, parent_folder_id: str, name: Optional[str] = None
    ) -> str:
        body = {"parents": [parent_folder_id]}
        if name:
            body["name"] = name
        copied = execute_with_retry(
            lambda: self._service.files()
            .copy(
                fileId=file_id,
                body=body,
                fields="id",
                supportsAllDrives=True,
            )
            .execute(),
            context=f"copying file {file_id} to folder {parent_folder_id}",
            retry=self._retry,
        )
        return copied["id"]

    def move_file(
        self, file_id: str, *, new_parent_id: str, remove_from_parents: bool = True
    ) -> None:
        file_meta = execute_with_retry(
            lambda: self._service.files()
            .get(fileId=file_id, fields="parents")
            .execute(),
            context=f"getting parents for file {file_id}",
            retry=self._retry,
        )
        previous_parents = ",".join(file_meta.get("parents", []))

        kwargs = {
            "fileId": file_id,
            "addParents": new_parent_id,
            "fields": "id, parents",
            "supportsAllDrives": True,
        }
        if remove_from_parents and previous_parents:
            kwargs["removeParents"] = previous_parents

        execute_with_retry(
            lambda: self._service.files().update(**kwargs).execute(),
            context=f"moving file {file_id} to folder {new_parent_id}",
            retry=self._retry,
        )

    def download_file(self, file_id: str, destination_path: str) -> None:
        # Chunked downloads happen client-side, but the initial request creation can fail.
        request = execute_with_retry(
            lambda: self._service.files().get_media(fileId=file_id),
            context=f"creating download request for file {file_id}",
            retry=self._retry,
        )
        with io.FileIO(destination_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()

    def upload_file(
        self,
        filepath: str,
        *,
        parent_id: str,
        dest_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> str:
        upload_name = dest_name or os.path.basename(filepath)
        file_metadata = {"name": upload_name, "parents": [parent_id]}
        media = MediaFileUpload(filepath, mimetype=mime_type, resumable=True)
        created = execute_with_retry(
            lambda: self._service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute(),
            context=f"uploading file {upload_name} to folder {parent_id}",
            retry=self._retry,
        )
        return created["id"]

    def delete_file(self, file_id: str) -> None:
        """Permanently delete a file from Google Drive.

        Use with care. This should only be called after a successful end-to-end process.
        """

        execute_with_retry(
            lambda: self._service.files()
            .delete(fileId=file_id, supportsAllDrives=True)
            .execute(),
            context=f"deleting file {file_id}",
            retry=self._retry,
        )


def get_drive_service():
    return google_api.get_drive_client()


def extract_date_from_filename(filename):
    import re

    match = re.match(r"(\d{4}-\d{2}-\d{2})", filename)
    return match.group(1) if match else filename


def delete_drive_file(service: Any, file_id: str) -> None:
    """
    Permanently delete a file from Google Drive.
    Only call this after a successful end-to-end process.
    """
    execute_with_retry(
        lambda: service.files()
        .delete(fileId=file_id, supportsAllDrives=True)
        .execute(),
        context=f"deleting file {file_id}",
        retry=RetryConfig(),
    )


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
    :param service: Google Drive API service instance.
    :param folder_id: The ID of the folder to list files from.
    :param mime_type_filter: Optional. If set, restricts results to this MIME type.
    :param include_all_drives: If True (default), includes files from all drives (Shared Drives support).
    :param include_folders: If False (default), excludes folders from results.
    :return: List of file dictionaries.
    """
    log.debug(
        f"list_files_in_folder called with folder_id={folder_id}, "
        f"mime_type_filter={mime_type_filter}, include_all_drives={include_all_drives}, include_folders={include_folders}"
    )
    query = f"'{folder_id}' in parents"
    if not include_folders:
        query += " and mimeType != 'application/vnd.google-apps.folder'"
    if mime_type_filter:
        query += f" and mimeType = '{mime_type_filter}'"
        log.debug(f"Applying mime_type_filter: {mime_type_filter}")
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
                f"Fetched {len(batch)} files (cumulative total: {len(files)}) from folder {folder_id}"
            )
            if page_token is None:
                break
        except Exception as e:
            log.error(f"Error listing files in folder {folder_id}: {e}")
            break
    log.info(f"Found {len(files)} files in folder {folder_id}.")
    if files:
        file_details = ", ".join(
            [f"{item.get('id', '?')}:{item.get('name', '?')}" for item in files]
        )
        log.debug(f"Files found: {file_details}")
    else:
        log.debug("No files found in folder.")
    return files


def list_music_files(service, folder_id):
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
    return results.get("files", [])


def get_or_create_folder(parent_folder_id: str, name: str, drive_service) -> str:
    """Returns the folder ID for a subfolder under parent_folder_id with the given name.
    Creates it if it doesn't exist, using an in-memory cache to avoid duplication."""
    cache_key = f"{parent_folder_id}/{name}"
    if cache_key in FOLDER_CACHE:
        return FOLDER_CACHE[cache_key]

    # Search for existing folder
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
        print(f"📁 Found existing folder '{name}' under parent {parent_folder_id}")
        folder_id = folders[0]["id"]
    else:
        print(f"📁 Creating new folder '{name}' under parent {parent_folder_id}")
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


def get_or_create_subfolder(drive_service, parent_folder_id, subfolder_name):
    """
    Gets or creates a subfolder inside a shared drive or My Drive.
    Returns the folder ID.
    """
    query = (
        f"mimeType='application/vnd.google-apps.folder' and "
        f"name='{subfolder_name}' and "
        f"'{parent_folder_id}' in parents and trashed=false"
    )
    response = (
        drive_service.files()
        .list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )

    files = response.get("files", [])
    if files:
        return files[0]["id"]

    file_metadata = {
        "name": subfolder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = (
        drive_service.files()
        .create(body=file_metadata, fields="id", supportsAllDrives=True)
        .execute()
    )

    return folder.get("id")


def get_file_by_name(drive_service, folder_id, filename):
    """
    Returns the file metadata for a file with a given name in a folder, or None if not found.
    """
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    response = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = response.get("files", [])
    if files:
        return files[0]
    return None


def get_all_subfolders(drive_service, parent_folder_id: str) -> List[Dict]:
    """
    Returns a list of all subfolders in the specified parent folder.
    Supports Shared Drives.
    """
    log.debug(
        f"📂 Retrieving all subfolders in folder ID {parent_folder_id} (shared drives enabled)"
    )
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
            folders.extend(response.get("files", []))
            page_token = response.get("nextPageToken", None)
            if page_token is None:
                break
        log.debug(f"📂 Found {len(folders)} subfolders under {parent_folder_id}")
        return folders
    except HttpError as error:
        log.error(f"An error occurred while retrieving subfolders: {error}")
        raise


def get_files_in_folder(
    service, folder_id, name_contains=None, mime_type=None, trashed=False
):
    """Returns a list of files in a Google Drive folder, optionally filtering by name substring and MIME type."""
    query = f"'{folder_id}' in parents"
    if name_contains:
        query += f" and name contains '{name_contains}'"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
    if trashed is False:
        query += " and trashed = false"

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

    return results.get("files", [])


def download_file(service, file_id, destination_path):
    """Download a file from Google Drive by ID using the Drive API."""
    log.debug(
        f"download_file called with file_id={file_id}, destination_path={destination_path}"
    )
    log.debug(f"Starting download for file_id={file_id} to {destination_path}")

    log.debug("Preparing request for file download")
    # Prepare request for file download
    request = service.files().get_media(fileId=file_id)

    # Attempt to open the destination file for writing
    try:
        fh = io.FileIO(destination_path, "wb")
        log.debug(f"Destination file {destination_path} opened for writing")
    except Exception as e:
        log.exception(f"Failed to open destination file {destination_path}")
        raise IOError(f"Could not create or write to file: {destination_path}") from e

    # Download file in chunks
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    chunk_count = 0
    log.debug("Beginning chunked download")
    while not done:
        status, done = downloader.next_chunk()
        chunk_count += 1
        progress_percent = int(status.progress() * 100) if status else 0
        log.debug(f"Chunk {chunk_count}: Download progress {progress_percent}%")
        log.debug(f"⬇️  Download {progress_percent}%.")
    log.info(f"Download complete for file_id={file_id} to {destination_path}")
    log.debug(f"Total chunks downloaded: {chunk_count}")


def upload_file(service, filepath, folder_id, dest_name: str | None = None) -> str:
    """
    Uploads a file to Google Drive into the given folder_id.

    By default, the uploaded Drive file name is the basename of filepath. If dest_name
    is provided, that name is used instead (useful when the local temp filename includes
    prefixes like a Drive file ID).

    Returns the uploaded Drive file ID.
    """
    upload_name = dest_name or os.path.basename(filepath)
    log.debug(f"Filepath: {filepath}, Folder ID: {folder_id}, Dest Name: {upload_name}")

    file_metadata = {"name": upload_name, "parents": [folder_id]}
    media = MediaFileUpload(filepath, resumable=True)

    created = (
        service.files()
        .create(
            body=file_metadata, media_body=media, fields="id", supportsAllDrives=True
        )
        .execute()
    )

    return created["id"]


def upload_to_drive(drive, filepath, parent_id):
    log.debug(f"Uploading file '{filepath}' to Drive folder ID '{parent_id}'")
    file_metadata = {
        "name": os.path.basename(filepath),
        "parents": [parent_id],
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    media = MediaFileUpload(filepath, mimetype="text/csv")
    uploaded = (
        drive.files()
        .create(
            body=file_metadata, media_body=media, fields="id", supportsAllDrives=True
        )
        .execute()
    )
    log.debug(f"📄 Uploaded to Drive as Google Sheet: {filepath}")
    log.debug(f"Uploaded file ID: {uploaded['id']}")

    # TODO - move this to a sheets function
    # After uploading, use gspread to open the sheet and check for 'sep=' in first row of all worksheets
    gc = google_sheets.get_gspread_client()
    spreadsheet = gc.open_by_key(uploaded["id"])
    for sheet in spreadsheet.worksheets():
        first_row = sheet.row_values(1)
        if first_row and first_row[0].strip().lower().startswith("sep="):
            sheet.delete_rows(1)

    return uploaded["id"]


def create_spreadsheet(
    drive_service,
    name,
    parent_folder_id,
    mime_type: str = "application/vnd.google-apps.spreadsheet",
):
    """
    Finds a file by name in the specified folder. If not found, creates a new file with that name.
    This function supports Shared Drives (supportsAllDrives=True).
    Returns the file ID.
    """
    log.debug(
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
            log.debug(f"📄 Found existing file '{name}' with ID {files[0]['id']}")
            return files[0]["id"]
        else:
            log.debug(
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
            log.debug(f"🆕 Created new file '{name}' with ID {file['id']}")
            return file["id"]
    except HttpError as error:
        log.error(f"An error occurred while finding or creating file: {error}")
        raise


def move_file_to_folder(drive_service, file_id, folder_id):
    """
    Moves a file to a specified folder.
    """
    # Get current parents
    file = drive_service.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file.get("parents", []))
    # Move the file to the new folder
    drive_service.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=previous_parents,
        fields="id, parents",
    ).execute()


def remove_file_from_root(drive_service, file_id):
    """
    Removes a file from the root folder.
    """
    file = drive_service.files().get(fileId=file_id, fields="parents").execute()
    parents = file.get("parents", [])
    if "root" in parents:
        drive_service.files().update(
            fileId=file_id, removeParents="root", fields="id, parents"
        ).execute()


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
    log.debug(
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
            log.debug(f"📄 Found existing file '{name}' with ID {files[0]['id']}")
            return files[0]["id"]
        else:
            log.debug(
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
            log.debug(f"🆕 Created new file '{name}' with ID {file['id']}")
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
            return files[0]["id"]
    except Exception as e:
        log.error(f"❌ Error finding subfolder '{subfolder_name}': {e}")
    return None
