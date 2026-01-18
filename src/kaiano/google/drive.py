import io
import os
import random
import time
from typing import Any, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from kaiano_common_utils import config
from kaiano_common_utils import logger as log

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
            safe_name_contains = name_contains.replace("'", "\\'")
            query += f" and name contains '{safe_name_contains}'"
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

        safe_name = name.replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents and name = '{safe_name}' "
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
        self,
        file_id: str,
        *,
        parent_folder_id: Optional[str] = None,
        name: Optional[str] = None,
        max_retries: int = 5,
    ) -> str:
        """Copy a Drive file.

        This method includes a small retry loop to handle Drive propagation delay where a
        just-created file may temporarily return a 404 "File not found" on copy.

        Backwards compatible with the previous signature; callers can still pass
        `parent_folder_id` and `name` as before.
        """

        body: dict[str, Any] = {}
        if parent_folder_id:
            body["parents"] = [parent_folder_id]
        if name:
            body["name"] = name

        delay = 1.0
        for attempt in range(max_retries):
            try:
                log.info(
                    f"📄 Copying file {file_id} → '{name if name else '(same name)'}' (attempt {attempt+1}/{max_retries})"
                )
                copied = execute_with_retry(
                    lambda: self._service.files()
                    .copy(
                        fileId=file_id,
                        body=body,
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute(),
                    context=f"copying file {file_id}",
                    retry=self._retry,
                )
                new_file_id = copied.get("id")
                if not new_file_id:
                    raise RuntimeError(
                        f"Drive copy did not return an id for source_file_id={file_id}"
                    )
                log.info(f"✅ File copied successfully: {new_file_id}")
                return new_file_id

            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status == 404 and "not found" in str(e).lower():
                    wait = delay + random.uniform(0, 0.5)
                    log.warning(
                        f"⚠️ File {file_id} not yet visible, retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})"
                    )
                    time.sleep(wait)
                    delay *= 2
                    continue
                raise

        raise RuntimeError(
            f"Failed to copy file {file_id} after {max_retries} attempts"
        )

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

    def update_file(
        self,
        file_id: str,
        filepath: str,
        *,
        mime_type: Optional[str] = None,
    ) -> None:
        """Upload a new version of an existing Drive file (in-place update)."""

        media = MediaFileUpload(filepath, mimetype=mime_type, resumable=True)

        execute_with_retry(
            lambda: self._service.files()
            .update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True,
            )
            .execute(),
            context=f"updating file {file_id} from {os.path.basename(filepath)}",
            retry=self._retry,
        )

    def rename_file(self, file_id: str, new_name: str) -> None:
        """Rename a Drive file."""

        execute_with_retry(
            lambda: self._service.files()
            .update(
                fileId=file_id,
                body={"name": new_name},
                supportsAllDrives=True,
            )
            .execute(),
            context=f"renaming file {file_id} to {new_name}",
            retry=self._retry,
        )

    def upload_csv_as_google_sheet(
        self,
        filepath: str,
        *,
        parent_id: str,
        dest_name: Optional[str] = None,
    ) -> str:
        """Upload a CSV and convert it to a Google Sheet in the destination folder."""

        upload_name = dest_name or os.path.basename(filepath)
        file_metadata = {
            "name": upload_name,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [parent_id],
        }

        # Upload the CSV but request Drive to convert it to a spreadsheet.
        media = MediaFileUpload(filepath, mimetype="text/csv", resumable=True)

        created = execute_with_retry(
            lambda: self._service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute(),
            context=f"uploading CSV as Google Sheet {upload_name} to folder {parent_id}",
            retry=self._retry,
        )

        return created["id"]

    def find_or_create_spreadsheet(self, *, parent_folder_id: str, name: str) -> str:
        """Find an existing spreadsheet by exact name in a folder, or create it."""

        safe_name = name.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' and '{parent_folder_id}' in parents and trashed = false "
            "and mimeType = 'application/vnd.google-apps.spreadsheet'"
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
            context=f"finding spreadsheet '{name}' under {parent_folder_id}",
            retry=self._retry,
        )

        files = resp.get("files", [])
        if files:
            return files[0]["id"]

        return self.create_spreadsheet_in_folder(name, parent_folder_id)

    def get_all_subfolders(self, parent_folder_id: str) -> list[DriveFile]:
        """Return all immediate subfolders of a parent folder (newest-first by modifiedTime)."""

        return self.list_files(
            parent_folder_id,
            mime_type="application/vnd.google-apps.folder",
            trashed=False,
            include_folders=True,
        )

    def get_files_in_folder(
        self, folder_id: str, *, include_folders: bool = True
    ) -> list[DriveFile]:
        """Return all immediate children in a folder (newest-first by modifiedTime)."""

        return self.list_files(
            folder_id,
            trashed=False,
            include_folders=include_folders,
        )

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

    def get_all_m3u_files(self) -> list[dict]:
        """Return all VirtualDJ history .m3u files (newest-first).

        Matches legacy `kaiano_common_utils.m3u_parsing.get_all_m3u_files(drive_service)`.

        Returns a list of dicts containing at least: {"id": str, "name": str}.
        Sorting is by filename. With date-prefixed filenames (YYYY-MM-DD.m3u), this
        yields correct chronological order.
        """

        if not getattr(config, "VDJ_HISTORY_FOLDER_ID", None):
            log.critical("VDJ_HISTORY_FOLDER_ID is not set in config.")
            return []

        try:
            files = self.list_files(
                config.VDJ_HISTORY_FOLDER_ID,
                name_contains=".m3u",
                trashed=False,
                include_folders=False,
            )

            files.sort(key=lambda f: f.name or "")
            files = list(reversed(files))

            return [{"id": f.id, "name": f.name} for f in files]
        except Exception as e:
            log.error(f"Failed to list .m3u files: {e}")
            return []

    def get_most_recent_m3u_file(self) -> dict | None:
        """Return the most recent .m3u file.

        Matches legacy `kaiano_common_utils.m3u_parsing.get_most_recent_m3u_file(drive_service)`.

        Returns a dict with keys: {"id", "name"} or None.
        """

        if not getattr(config, "VDJ_HISTORY_FOLDER_ID", None):
            log.critical("VDJ_HISTORY_FOLDER_ID is not set in config.")
            return None

        try:
            files = self.list_files(
                config.VDJ_HISTORY_FOLDER_ID,
                name_contains=".m3u",
                trashed=False,
                include_folders=False,
            )

            if not files:
                return None

            files.sort(key=lambda f: f.name or "")
            f = files[-1]
            return {"id": f.id, "name": f.name}
        except Exception as e:
            log.error(f"Failed to find most recent .m3u file: {e}")
            return None

    def download_m3u_file_data(
        self, file_id: str, *, encoding: str = "utf-8"
    ) -> list[str]:
        """Download a .m3u file and return its lines."""

        try:
            # The initial request creation can fail; download itself is chunked.
            request = execute_with_retry(
                lambda: self._service.files().get_media(fileId=file_id),
                context=f"creating download request for file {file_id}",
                retry=self._retry,
            )

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()

            return fh.getvalue().decode(encoding).splitlines()
        except Exception as e:
            log.error(f"Failed to download .m3u file with ID {file_id}: {e}")
            return []

    def create_spreadsheet_in_folder(self, name: str, folder_id: str) -> str:
        """Create a Google Sheet in the given Drive folder and return its file ID."""
        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [folder_id],
        }

        created = execute_with_retry(
            lambda: self._service.files()
            .create(
                body=body,
                fields="id",
                supportsAllDrives=True,
            )
            .execute(),
            context=f"creating spreadsheet '{name}' in folder {folder_id}",
            retry=self._retry,
        )

        return created["id"]
