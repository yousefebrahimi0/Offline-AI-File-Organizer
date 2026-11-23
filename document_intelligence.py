"""Optional local OCR and low-payload image preparation.

No heavyweight OCR model is downloaded. PyMuPDF, Tesseract, and Pillow are optional.
"""

from __future__ import annotations

import base64
import io
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


def image_ocr(path: Path, max_chars: int = 1200) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            text = pytesseract.image_to_string(image)
            return text.strip()[:max_chars]
    except (ImportError, OSError, RuntimeError, ValueError):
        return ""
    except Exception:
        # TesseractNotFoundError and unsupported input formats should not stop analysis.
        return ""


def scanned_pdf_ocr(path: Path, max_pages: int = 2, max_chars: int = 1800) -> str:
    """OCR only scanned pages after normal PDF text extraction found no text."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        snippets = []
        with fitz.open(str(path)) as document:
            for page in list(document)[:max_pages]:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                text = pytesseract.image_to_string(image).strip()
                if text:
                    snippets.append(text)
                if sum(map(len, snippets)) >= max_chars:
                    break
        return " ".join(snippets)[:max_chars]
    except Exception:
        # Missing executables/libraries and malformed PDFs fall back to normal extraction.
        return ""


def exif_hint(path: Path) -> str:
    """Expose only useful capture timing; never leak GPS coordinates to the model."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            exif = image.getexif()
            date = exif.get(36867) or exif.get(306)
            if isinstance(date, str) and len(date) >= 10:
                return f"Photo capture date: {date[:10].replace(':', '-')}"
    except Exception:
        pass
    return ""


def optimized_image(path: Path, max_dimension: int = 1024, quality: int = 76) -> Tuple[str, str]:
    """Resize an image in memory before a multimodal API request, never editing originals.

    Resizing usually reduces image bytes. Actual billed tokens depend on the provider.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original)
            image.thumbnail((max(256, int(max_dimension)), max(256, int(max_dimension))))
            is_alpha = "A" in image.getbands()
            output = io.BytesIO()
            if is_alpha:
                image.save(output, format="PNG", optimize=True)
                mime = "image/png"
            else:
                image.convert("RGB").save(output, format="JPEG", quality=max(40, min(90, int(quality))), optimize=True)
                mime = "image/jpeg"
            return mime, base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        return mime, base64.b64encode(path.read_bytes()).decode("ascii")



def document_hints(content: str) -> dict:
    """Conservative local date/vendor/invoice hints; not verified invoice fields."""
    hints = {}
    patterns = [
        (r"\b(20\d{2}-\d{2}-\d{2})\b", "%Y-%m-%d"),
        (r"\b([0-3]?\d/[01]?\d/20\d{2})\b", "%d/%m/%Y"),
        (r"\b([0-3]?\d\.[01]?\d\.20\d{2})\b", "%d.%m.%Y"),
    ]
    for pattern, date_format in patterns:
        match = re.search(pattern, content)
        if match:
            try:
                hints["document_date"] = datetime.strptime(match.group(1), date_format).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    vendor = re.search(
        r"(?:supplier|vendor|merchant|fornecedor)\s*:\s*([^\n]{3,60})",
        content[:1200], re.IGNORECASE,
    )
    if vendor:
        hints["vendor"] = vendor.group(1).strip().split("|")[0][:50]

    number = re.search(
        r"(?:invoice|fatura)\s*(?:number|no\.?|n[ºo]?)\s*[:#-]?\s*([A-Za-z0-9-]{2,30})",
        content[:1200], re.IGNORECASE,
    )
    if number:
        hints["invoice_number"] = number.group(1)
    return hints
