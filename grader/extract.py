from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .types import ExtractedPdf


def extract_pdf_text(
    pdf_path: Path,
    temp_dir: Path,
    ocr_char_threshold: int = 200,
) -> ExtractedPdf:
    native_text = run_pdftotext(pdf_path)
    native_chars = non_whitespace_char_count(native_text)

    if native_chars >= ocr_char_threshold:
        return ExtractedPdf(
            pdf_path=pdf_path,
            text=native_text,
            source="pdftotext",
            native_char_count=native_chars,
            ocr_char_count=0,
        )

    try:
        ocr_text = run_ocr_all_pages(pdf_path, temp_dir=temp_dir)
    except Exception:
        # OCR failures should not abort the whole grading run.
        ocr_text = ""
    ocr_chars = non_whitespace_char_count(ocr_text)
    best_text = ocr_text if ocr_chars > native_chars else native_text
    source = "ocr" if ocr_chars > native_chars else "pdftotext"
    return ExtractedPdf(
        pdf_path=pdf_path,
        text=best_text,
        source=source,
        native_char_count=native_chars,
        ocr_char_count=ocr_chars,
    )


def run_pdftotext(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    # pdftotext may emit syntax warnings on stderr but still return useful text.
    return result.stdout or ""


def run_ocr_all_pages(pdf_path: Path, temp_dir: Path) -> str:
    temp_dir.mkdir(parents=True, exist_ok=True)
    page_count = get_pdf_page_count(pdf_path)
    chunks: list[str] = []
    for page_num in range(1, page_count + 1):
        safe_stem = sanitize_for_filename(pdf_path.stem)
        unique = f"{safe_stem}_{page_num}_{uuid.uuid4().hex[:8]}"
        out_prefix = temp_dir / unique
        png_path = png_output_path(out_prefix)
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_num),
                "-l",
                str(page_num),
                "-singlefile",
                "-png",
                str(pdf_path),
                str(out_prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            ocr = subprocess.run(
                ["tesseract", str(png_path), "stdout", "--dpi", "300"],
                check=True,
                capture_output=True,
                text=True,
            )
            chunks.append(ocr.stdout or "")
        finally:
            safe_unlink(png_path)
    return "\n".join(chunks)


def get_pdf_page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.lower().startswith("pages:"):
            return int(line.split(":", 1)[1].strip())
    return 1


def non_whitespace_char_count(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return


def sanitize_for_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return sanitized or "document"


def png_output_path(prefix: Path) -> Path:
    return Path(f"{prefix}.png")


def ensure_binaries_present() -> list[str]:
    missing = []
    for command in ("pdftotext", "pdfinfo", "pdftoppm", "tesseract"):
        if shutil.which(command) is None:
            missing.append(command)
    return missing
