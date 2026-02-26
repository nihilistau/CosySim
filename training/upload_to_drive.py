"""
Upload training datasets to Google Drive for Colab fine-tuning.

Syncs training/datasets/*.jsonl to Google Drive via the Drive API,
so the Colab notebook can access them without manual upload.

Prerequisites:
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

Usage:
    python -m training.upload_to_drive                    # upload all datasets
    python -m training.upload_to_drive --only tag_extraction
    python -m training.upload_to_drive --drive-folder cosysim_training
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"
DEFAULT_DRIVE_FOLDER = "cosysim_training"


def upload_via_gdrive_api(
    folder_name: str = DEFAULT_DRIVE_FOLDER,
    only: Optional[str] = None,
) -> dict:
    """Upload datasets using Google Drive API (requires OAuth)."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        raise ImportError(
            "Install Google Drive API: pip install google-api-python-client "
            "google-auth-httplib2 google-auth-oauthlib"
        )

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]
    creds = None
    token_path = Path(__file__).parent / ".gdrive_token.json"
    creds_path = Path(__file__).parent / "credentials.json"

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"No {creds_path}. Download OAuth credentials from "
                    "Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    service = build("drive", "v3", credentials=creds)

    # Find or create folder
    results = service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces="drive", fields="files(id, name)",
    ).execute()

    if results.get("files"):
        folder_id = results["files"][0]["id"]
    else:
        folder_meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(body=folder_meta, fields="id").execute()
        folder_id = folder["id"]
        log.info("Created Drive folder: %s (%s)", folder_name, folder_id)

    # Upload datasets
    files = sorted(DATASETS_DIR.glob("*.jsonl"))
    if only:
        files = [f for f in files if only in f.stem]

    uploaded = {}
    for filepath in files:
        media = MediaFileUpload(str(filepath), mimetype="application/jsonl")
        # Check if file already exists
        existing = service.files().list(
            q=f"name='{filepath.name}' and '{folder_id}' in parents and trashed=false",
            spaces="drive", fields="files(id)",
        ).execute()

        if existing.get("files"):
            service.files().update(
                fileId=existing["files"][0]["id"], media_body=media,
            ).execute()
            log.info("Updated: %s", filepath.name)
        else:
            file_meta = {"name": filepath.name, "parents": [folder_id]}
            service.files().create(body=file_meta, media_body=media, fields="id").execute()
            log.info("Uploaded: %s", filepath.name)

        uploaded[filepath.name] = filepath.stat().st_size

    return {"folder": folder_name, "folder_id": folder_id, "files": uploaded}


def upload_via_copy(
    drive_mount: str = "G:\\My Drive",
    folder_name: str = DEFAULT_DRIVE_FOLDER,
    only: Optional[str] = None,
) -> dict:
    """Upload by copying to mounted Google Drive (Drive for Desktop)."""
    target = Path(drive_mount) / folder_name
    target.mkdir(parents=True, exist_ok=True)

    files = sorted(DATASETS_DIR.glob("*.jsonl"))
    if only:
        files = [f for f in files if only in f.stem]

    uploaded = {}
    for filepath in files:
        dest = target / filepath.name
        shutil.copy2(filepath, dest)
        uploaded[filepath.name] = filepath.stat().st_size
        log.info("Copied: %s → %s", filepath.name, dest)

    return {"folder": str(target), "files": uploaded}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Upload training data to Google Drive")
    parser.add_argument("--only", help="Only upload this dataset (substring match)")
    parser.add_argument("--drive-folder", default=DEFAULT_DRIVE_FOLDER)
    parser.add_argument("--method", choices=["api", "copy", "auto"], default="auto",
                        help="Upload method: api (OAuth), copy (mounted drive), auto")
    parser.add_argument("--drive-mount", default="G:\\My Drive",
                        help="Drive for Desktop mount point (for 'copy' method)")
    args = parser.parse_args()

    if args.method == "copy" or (args.method == "auto" and Path(args.drive_mount).exists()):
        result = upload_via_copy(args.drive_mount, args.drive_folder, args.only)
        print(f"Copied {len(result['files'])} files to {result['folder']}")
    else:
        result = upload_via_gdrive_api(args.drive_folder, args.only)
        print(f"Uploaded {len(result['files'])} files to Drive folder '{result['folder']}'")

    total_bytes = sum(result["files"].values())
    print(f"Total: {total_bytes / 1024:.1f} KB")
    for name, size in result["files"].items():
        print(f"  {name}: {size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
