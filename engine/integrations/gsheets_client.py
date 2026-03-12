"""Google Sheets API client via sheets.googleapis.com and clients6.google.com.

Provides spreadsheet creation, reading, writing, and management using the
same Google session cookies used for Drive and NotebookLM integrations.

All endpoints use the Sheets v4 API and Drive v3 for file-level operations.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from engine.integrations.google_account_pool import GoogleAccount, get_account_pool

logger = logging.getLogger(__name__)

# ──── Constants ───────────────────────────────────────────────────────────────

_SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
_DRIVE_BASE = "https://clients6.google.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://clients6.google.com/upload/drive/v3"
_SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
_SHEETS_ORIGIN = "https://docs.google.com"
_SHEETS_REFERER = "https://docs.google.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


# ──── Client ─────────────────────────────────────────────────────────────────

class GoogleSheetsClient:
    """Google Sheets API client using browser session cookies.

    Args:
        account: Authenticated GoogleAccount from the pool.
    """

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ──── Auth ────────────────────────────────────────────────────────────────

    def _get_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build request headers with SAPISIDHASH auth.

        Args:
            extra: Additional headers to merge in.

        Returns:
            Complete headers dict.
        """
        pool = get_account_pool()
        cookie_header = pool.get_cookie_header(self._account)
        sapisid = self._account.cookies.get("SAPISID", "")
        sapisid1p = self._account.cookies.get("__Secure-1PAPISID", sapisid)
        sapisid3p = self._account.cookies.get("__Secure-3PAPISID", sapisid)

        ts = str(int(time.time()))
        origin = _SHEETS_ORIGIN

        def _hash(key: str, prefix: str = "SAPISIDHASH") -> str:
            digest = hashlib.sha1(f"{ts} {key} {origin}".encode()).hexdigest()
            return f"{prefix} {ts}_{digest}"

        auth_parts = []
        if sapisid:
            auth_parts.append(_hash(sapisid))
        if sapisid1p:
            auth_parts.append(_hash(sapisid1p, "SAPISID1PHASH"))
        if sapisid3p:
            auth_parts.append(_hash(sapisid3p, "SAPISID3PHASH"))

        headers: Dict[str, str] = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": cookie_header,
            "Origin": origin,
            "Referer": _SHEETS_REFERER,
            "X-Goog-Authuser": str(self._account.authuser),
            "X-Same-Domain": "1",
        }
        if auth_parts:
            headers["Authorization"] = " ".join(auth_parts)
        if extra:
            headers.update(extra)
        return headers

    # ──── Sheet creation ──────────────────────────────────────────────────────

    def create_sheet(
        self,
        title: str,
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new Google Sheets spreadsheet in Drive.

        Args:
            title: Spreadsheet title.
            folder_id: Optional parent folder ID to place the sheet in.

        Returns:
            Dict with id, name, mimeType, and url of the created spreadsheet.
        """
        metadata: Dict[str, Any] = {"name": title, "mimeType": _SHEETS_MIME}
        if folder_id:
            metadata["parents"] = [folder_id]

        headers = self._get_headers({"Content-Type": "application/json"})
        params = {"fields": "id,name,mimeType"}
        resp = self._session.post(
            f"{_DRIVE_BASE}/files",
            headers=headers,
            params=params,
            json=metadata,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        sheet_id = data["id"]
        data["url"] = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        logger.info("Created Google Sheet: %s (%s)", title, sheet_id)
        return data

    # ──── Metadata ────────────────────────────────────────────────────────────

    def get_metadata(self, sheet_id: str) -> Dict[str, Any]:
        """Get spreadsheet metadata including sheet tab info.

        Args:
            sheet_id: The spreadsheet ID.

        Returns:
            Raw metadata dict with spreadsheetId, properties, and sheets.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        params = {"fields": "spreadsheetId,properties,sheets"}
        resp = self._session.get(
            f"{_SHEETS_API}/{sheet_id}",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ──── Reading ─────────────────────────────────────────────────────────────

    def read_rows(
        self,
        sheet_id: str,
        range_: str = "Sheet1",
        include_headers: bool = True,
    ) -> List[Any]:
        """Read rows from a sheet range.

        Args:
            sheet_id: The spreadsheet ID.
            range_: A1 notation range or sheet name (default: "Sheet1").
            include_headers: If True, treat first row as keys and return list
                of dicts. If False, return list of dicts with first row as keys
                is skipped — use read_raw instead for raw lists.

        Returns:
            List of dicts (include_headers=True) or list of lists (False).
        """
        raw = self.read_raw(sheet_id, range_)
        if not raw:
            return []
        if not include_headers:
            return raw
        headers = raw[0]
        result = []
        for row in raw[1:]:
            # Pad row to header length so zip always produces full dicts
            padded = row + [""] * (len(headers) - len(row))
            result.append(dict(zip(headers, padded)))
        return result

    def read_raw(self, sheet_id: str, range_: str = "Sheet1") -> List[List[str]]:
        """Read raw cell values from a sheet range.

        Args:
            sheet_id: The spreadsheet ID.
            range_: A1 notation range or sheet name (default: "Sheet1").

        Returns:
            List of rows, where each row is a list of string cell values.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        resp = self._session.get(
            f"{_SHEETS_API}/{sheet_id}/values/{range_}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("values", [])

    # ──── Writing ─────────────────────────────────────────────────────────────

    def append_rows(
        self,
        sheet_id: str,
        rows: List[Dict[str, Any]],
        sheet_name: str = "Sheet1",
    ) -> Dict[str, Any]:
        """Append rows of data to a sheet.

        Detects whether the sheet is empty and writes headers first if needed.
        Headers are derived from the keys of the first dict in rows.

        Args:
            sheet_id: The spreadsheet ID.
            rows: List of dicts to append. All dicts should share the same keys.
            sheet_name: Target sheet tab name (default: "Sheet1").

        Returns:
            API response dict with updatedRows and other update metadata.
        """
        if not rows:
            return {"updatedRows": 0}

        col_headers = list(rows[0].keys())
        existing = self.read_raw(sheet_id, sheet_name)
        values: List[List[Any]] = []

        if not existing:
            values.append(col_headers)

        for row in rows:
            values.append([row.get(h, "") for h in col_headers])

        headers = self._get_headers({"Content-Type": "application/json"})
        range_notation = f"{sheet_name}!A1"
        params = {
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
        }
        body = {"values": values}
        resp = self._session.post(
            f"{_SHEETS_API}/{sheet_id}/values/{range_notation}:append",
            headers=headers,
            params=params,
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug(
            "Appended %d rows to %s/%s", len(rows), sheet_id, sheet_name
        )
        return data

    def write_rows(
        self,
        sheet_id: str,
        rows: List[Dict[str, Any]],
        sheet_name: str = "Sheet1",
        start_row: int = 1,
    ) -> Dict[str, Any]:
        """Write rows to a sheet, overwriting from the given start row.

        Writes headers at start_row, then data in subsequent rows.

        Args:
            sheet_id: The spreadsheet ID.
            rows: List of dicts to write. Keys become column headers.
            sheet_name: Target sheet tab name (default: "Sheet1").
            start_row: 1-based row index to begin writing (default: 1).

        Returns:
            API response dict with updatedRows and other update metadata.
        """
        if not rows:
            return {"updatedRows": 0}

        col_headers = list(rows[0].keys())
        values: List[List[Any]] = [col_headers]
        for row in rows:
            values.append([row.get(h, "") for h in col_headers])

        headers = self._get_headers({"Content-Type": "application/json"})
        range_notation = f"{sheet_name}!A{start_row}"
        params = {"valueInputOption": "USER_ENTERED"}
        body = {"values": values}
        resp = self._session.put(
            f"{_SHEETS_API}/{sheet_id}/values/{range_notation}",
            headers=headers,
            params=params,
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug(
            "Wrote %d rows to %s/%s starting at row %d",
            len(rows),
            sheet_id,
            sheet_name,
            start_row,
        )
        return data

    # ──── Clear ───────────────────────────────────────────────────────────────

    def clear_sheet(self, sheet_id: str, sheet_name: str = "Sheet1") -> bool:
        """Clear all values from a sheet tab.

        Args:
            sheet_id: The spreadsheet ID.
            sheet_name: Target sheet tab name (default: "Sheet1").

        Returns:
            True if cleared successfully, False on failure.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        try:
            resp = self._session.post(
                f"{_SHEETS_API}/{sheet_id}/values/{sheet_name}:clear",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            logger.debug("Cleared sheet %s/%s", sheet_id, sheet_name)
            return True
        except Exception as exc:
            logger.warning("Failed to clear sheet %s/%s: %s", sheet_id, sheet_name, exc)
            return False

    # ──── Composite helpers ───────────────────────────────────────────────────

    def create_from_data(
        self,
        title: str,
        rows: List[Dict[str, Any]],
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new spreadsheet and populate it with rows in one call.

        Args:
            title: Spreadsheet title.
            rows: List of dicts to write as data rows.
            folder_id: Optional parent folder ID.

        Returns:
            Dict with id, url, and rows_written count.
        """
        sheet = self.create_sheet(title, folder_id=folder_id)
        sheet_id = sheet["id"]
        result = self.append_rows(sheet_id, rows)
        rows_written = result.get("updates", {}).get("updatedRows", len(rows))
        return {
            "id": sheet_id,
            "url": sheet["url"],
            "rows_written": rows_written,
        }

    # ──── Sharing ─────────────────────────────────────────────────────────────

    def get_shareable_url(self, sheet_id: str) -> str:
        """Build a shareable URL for a spreadsheet.

        Args:
            sheet_id: The spreadsheet ID.

        Returns:
            Shareable URL string.
        """
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit?usp=sharing"

    def make_public(self, sheet_id: str) -> bool:
        """Set a spreadsheet's permission so anyone with the link can read it.

        Args:
            sheet_id: The spreadsheet ID.

        Returns:
            True if permission was set successfully, False on failure.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        body = {"type": "anyone", "role": "reader"}
        try:
            resp = self._session.post(
                f"{_DRIVE_BASE}/files/{sheet_id}/permissions",
                headers=headers,
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("Made sheet %s publicly readable", sheet_id)
            return True
        except Exception as exc:
            logger.warning("Failed to set public permission on %s: %s", sheet_id, exc)
            return False

    # ──── Export ──────────────────────────────────────────────────────────────

    def export_as_csv(self, sheet_id: str, sheet_name: str = "Sheet1") -> str:
        """Export a sheet tab as a CSV string.

        Args:
            sheet_id: The spreadsheet ID.
            sheet_name: Tab name to export (default: "Sheet1").

        Returns:
            CSV content as a string.
        """
        headers = self._get_headers()
        params = {"format": "csv", "sheet": sheet_name}
        resp = self._session.get(
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/export",
            headers=headers,
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.text

    # ──── Gemini Integration ─────────────────────────────────────────────────

    def fill_with_gemini(
        self,
        sheet_id: str,
        range_: str,
        prompt: str,
        sheet_name: str = "Sheet1",
    ) -> Dict[str, Any]:
        """Fill a range with Gemini-generated data.

        Uses the Workspace Gemini ``streamGenerate`` endpoint to generate
        structured data and writes it into the specified range.  Mirrors the
        "Fill with Gemini" feature in Sheets.

        Args:
            sheet_id: The spreadsheet ID.
            range_: Target range in A1 notation (e.g. "B2:D10").
            prompt: Prompt describing what data to generate.
            sheet_name: Target sheet tab name (default: "Sheet1").

        Returns:
            Dict with generated text, rows written count, and sheet_id.
        """
        from engine.integrations.workspace_gemini_client import (
            WorkspaceGeminiClient,
        )

        existing = self.read_raw(sheet_id, sheet_name)
        context = json.dumps(existing[:20]) if existing else None

        gemini = WorkspaceGeminiClient(account=self._account)
        result = gemini.stream_generate(
            prompt=f"For a Google Sheets spreadsheet, {prompt}. Return data as "
                   f"tab-separated rows suitable for pasting into cells.",
            context=context,
            document_id=sheet_id,
            document_type="sheets",
        )

        text = result.get("text", "")
        rows_written = 0
        if text:
            parsed_rows = self._parse_tsv(text)
            if parsed_rows:
                full_range = f"{sheet_name}!{range_}"
                headers = self._get_headers({"Content-Type": "application/json"})
                params = {"valueInputOption": "USER_ENTERED"}
                body = {"values": parsed_rows}
                try:
                    resp = self._session.put(
                        f"{_SHEETS_API}/{sheet_id}/values/{full_range}",
                        headers=headers,
                        params=params,
                        json=body,
                        timeout=60,
                    )
                    resp.raise_for_status()
                    rows_written = len(parsed_rows)
                except requests.RequestException as exc:
                    logger.error("fill_with_gemini write failed: %s", exc)

        return {
            "sheet_id": sheet_id,
            "text": text,
            "rows_written": rows_written,
            "model": result.get("model", ""),
        }

    def build_with_gemini(
        self,
        prompt: str,
        title: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an entire spreadsheet from a prompt using Gemini.

        Mirrors the "Build with Gemini" feature that generates a complete
        spreadsheet structure (headers, formulas, data) from a natural
        language description.

        Args:
            prompt: Description of the desired spreadsheet.
            title: Optional spreadsheet title.  If None, Gemini generates one.
            folder_id: Optional parent folder ID.

        Returns:
            Dict with id, url, title, rows_written, and generation result.
        """
        from engine.integrations.workspace_gemini_client import (
            WorkspaceGeminiClient,
        )

        gemini = WorkspaceGeminiClient(account=self._account)
        result = gemini.stream_generate(
            prompt=f"Build a complete Google Sheets spreadsheet for: {prompt}. "
                   f"Include headers and sample data. Format as tab-separated "
                   f"values with the first row as column headers.",
            document_type="sheets",
        )

        text = result.get("text", "")
        if not title:
            title = prompt[:60].strip().replace("\n", " ")

        sheet = self.create_sheet(title, folder_id=folder_id)
        sheet_id = sheet["id"]
        rows_written = 0

        if text:
            parsed_rows = self._parse_tsv(text)
            if parsed_rows:
                write_result = self.write_rows(
                    sheet_id,
                    [{f"col_{i}": v for i, v in enumerate(row)} for row in parsed_rows[:1]],
                )
                if len(parsed_rows) > 1:
                    headers_list = parsed_rows[0]
                    data_dicts = [
                        {headers_list[i] if i < len(headers_list) else f"col_{i}": v
                         for i, v in enumerate(row)}
                        for row in parsed_rows[1:]
                    ]
                    self.write_rows(sheet_id, data_dicts, start_row=2)
                rows_written = len(parsed_rows)

        return {
            "id": sheet_id,
            "url": sheet["url"],
            "title": title,
            "rows_written": rows_written,
            "model": result.get("model", ""),
        }

    def execute_columnsmith(
        self,
        sheet_id: str,
        column_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a column transformation via the columnsmith endpoint.

        This endpoint handles AI-powered column formula/transformation
        operations in Google Sheets.

        Args:
            sheet_id: The spreadsheet ID.
            column_spec: Column transformation specification dict containing
                the column index, formula type, and parameters.

        Returns:
            API response dict with transformation results.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        try:
            resp = self._session.post(
                f"https://docs.google.com/spreadsheets/u/0/d/{sheet_id}/columnsmith/execute",
                headers=headers,
                json=column_spec,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("columnsmith execute failed: %s", exc)
            return {"error": str(exc)}

    def fetch_external_data(
        self,
        sheet_id: str,
        source_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fetch data from external sources into the spreadsheet.

        Uses the externaldata/fetchData endpoint that powers web data
        import and enrichment in Sheets.

        Args:
            sheet_id: The spreadsheet ID.
            source_spec: External data source specification.

        Returns:
            API response dict with fetched data.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        try:
            resp = self._session.post(
                f"https://docs.google.com/spreadsheets/u/0/d/{sheet_id}/externaldata/fetchData",
                headers=headers,
                json=source_spec,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("externaldata fetchData failed: %s", exc)
            return {"error": str(exc)}

    @staticmethod
    def _parse_tsv(text: str) -> List[List[str]]:
        """Parse tab-separated or pipe-separated text into rows.

        Handles various formats that Gemini might return including TSV,
        pipe-separated tables, and comma-separated values.

        Args:
            text: Raw text output from Gemini.

        Returns:
            List of rows, where each row is a list of cell values.
        """
        rows: List[List[str]] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("---") or line.startswith("==="):
                continue
            if "\t" in line:
                cells = [c.strip() for c in line.split("\t")]
            elif "|" in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
            else:
                cells = [c.strip() for c in line.split(",")]
            if cells:
                rows.append(cells)
        return rows

    # ──── Tab management ──────────────────────────────────────────────────────

    def list_sheets(self, sheet_id: str) -> List[str]:
        """Return the names of all tabs in a spreadsheet.

        Args:
            sheet_id: The spreadsheet ID.

        Returns:
            List of sheet tab name strings.
        """
        metadata = self.get_metadata(sheet_id)
        return [
            s["properties"]["title"]
            for s in metadata.get("sheets", [])
        ]

    def add_sheet_tab(self, sheet_id: str, tab_name: str) -> bool:
        """Add a new tab to an existing spreadsheet.

        Args:
            sheet_id: The spreadsheet ID.
            tab_name: Name for the new tab.

        Returns:
            True if added successfully, False on failure.
        """
        headers = self._get_headers({"Content-Type": "application/json"})
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {"title": tab_name}
                    }
                }
            ]
        }
        try:
            resp = self._session.post(
                f"{_SHEETS_API}/{sheet_id}:batchUpdate",
                headers=headers,
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("Added tab '%s' to sheet %s", tab_name, sheet_id)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to add tab '%s' to sheet %s: %s", tab_name, sheet_id, exc
            )
            return False


# ──── Factory ─────────────────────────────────────────────────────────────────

def get_sheets_client(
    account_name: Optional[str] = None,
) -> Optional[GoogleSheetsClient]:
    """Get a GoogleSheetsClient for the named account or the next available one.

    Args:
        account_name: Specific account name, or None for round-robin selection.

    Returns:
        GoogleSheetsClient, or None if no account is available.
    """
    pool = get_account_pool()

    if account_name:
        account = pool.get_by_name(account_name)
    else:
        account = (
            pool.get_account("sheets")
            or pool.get_account("drive")
            or pool.get_account("colab")
            or pool.get_account("notebooklm")
        )

    if account is None:
        logger.warning(
            "No Sheets account available (requested: %s). "
            "Import an account with: pool.import_from_har(har_path, name, ['sheets'])",
            account_name,
        )
        return None

    return GoogleSheetsClient(account)
