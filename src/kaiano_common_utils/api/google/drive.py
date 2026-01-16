import io
import os
from typing import Any, Optional

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

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
