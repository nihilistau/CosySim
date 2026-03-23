"""
Assistant Platform — File Upload Handler
==========================================

Processes file uploads: save, extract text, return metadata.

Version: v1.0.0 [2026-03-23]
Author:  CosySim Team

Change Log:
    v1.0.0 [2026-03-23] — Initial file handler
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from apps.assistant.config import UPLOAD_DIR

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    # Text
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".html", ".css", ".xml", ".sql",
    ".sh", ".bat", ".ps1", ".log", ".ini", ".cfg", ".conf",
    # Documents
    ".pdf",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
}


def handle_upload(file_storage: Any) -> Dict[str, Any]:
    """Save an uploaded file and return metadata.

    Args:
        file_storage: Flask FileStorage object from request.files

    Returns:
        Dict with id, filename, original_name, path, size, type, text_content
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    original_name = file_storage.filename or "unnamed"
    suffix = Path(original_name).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        return {"error": f"File type {suffix} not allowed"}

    file_id = str(uuid.uuid4())
    save_name = f"{file_id}{suffix}"
    save_path = UPLOAD_DIR / save_name

    file_storage.save(str(save_path))
    size = save_path.stat().st_size

    # Extract text content for text-based files
    text_content = None
    if suffix in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml",
                  ".py", ".js", ".ts", ".html", ".css", ".xml", ".sql",
                  ".sh", ".bat", ".ps1", ".log", ".ini", ".cfg", ".conf"}:
        text_content = extract_text(str(save_path))
    elif suffix == ".pdf":
        text_content = extract_pdf_text(str(save_path))

    file_type = "image" if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"} else "document"

    logger.info(
        "[FileHandler] Uploaded %s (%s, %d bytes)",
        original_name, file_type, size,
    )

    return {
        "id": file_id,
        "filename": save_name,
        "original_name": original_name,
        "path": str(save_path),
        "size": size,
        "type": file_type,
        "suffix": suffix,
        "text_content": text_content,
    }


def extract_text(file_path: str) -> Optional[str]:
    """Extract text content from a text-based file."""
    try:
        return Path(file_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.debug("[FileHandler] Text extraction failed for %s: %s", file_path, e)
        return None


def extract_pdf_text(file_path: str) -> Optional[str]:
    """Extract text from a PDF file."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        # Try pdfplumber as fallback
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                return "\n\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        except ImportError:
            logger.debug("[FileHandler] No PDF library available (install pymupdf or pdfplumber)")
            return "(PDF text extraction requires pymupdf: pip install pymupdf)"
    except Exception as e:
        logger.debug("[FileHandler] PDF extraction failed: %s", e)
        return None
