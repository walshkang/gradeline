from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .types import ExtractedPdf, TextBlock


def parse_tsv_blocks(tsv_text: str, page: int, dpi: float) -> list[TextBlock]:
    lines = tsv_text.splitlines()
    if not lines:
        return []

    # Skip header row; columns:
    # level, page_num, block_num, par_num, line_num, word_num, left, top, width, height, conf, text
    groups: dict[int, list[dict]] = {}
    for line in lines[1:]:
        parts = line.split("\t", 11)
        if len(parts) < 12:
            continue
        try:
            level = int(parts[0])
        except ValueError:
            continue
        if level != 5:
            continue
        text = parts[11]
        if not text.strip():
            continue
        try:
            block_num = int(parts[2])
            left = float(parts[6])
            top = float(parts[7])
            width = float(parts[8])
            height = float(parts[9])
            conf = float(parts[10])
        except ValueError:
            continue
        groups.setdefault(block_num, []).append(
            {"text": text, "left": left, "top": top, "width": width, "height": height, "conf": conf}
        )

    blocks: list[TextBlock] = []
    for block_num, words in sorted(groups.items()):
        joined_text = " ".join(w["text"] for w in words)
        min_left = min(w["left"] for w in words)
        min_top = min(w["top"] for w in words)
        max_right = max(w["left"] + w["width"] for w in words)
        max_bottom = max(w["top"] + w["height"] for w in words)
        mean_conf = sum(w["conf"] for w in words) / len(words)
        blocks.append(
            TextBlock(
                id=f"p{page}_b{block_num}",
                text=joined_text,
                page=page,
                left=min_left,
                top=min_top,
                width=max_right - min_left,
                height=max_bottom - min_top,
                source="tesseract_tsv",
                confidence=mean_conf,
            )
        )
    return blocks


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
            blocks=[],
            text=native_text,
            source="pdftotext",
            native_char_count=native_chars,
            ocr_char_count=0,
        )

    try:
        ocr_blocks = run_ocr_all_pages(pdf_path, temp_dir=temp_dir)
    except Exception:
        # OCR failures should not abort the whole grading run.
        ocr_blocks = []
    ocr_text = "\n".join(b.text for b in ocr_blocks)
    ocr_chars = non_whitespace_char_count(ocr_text)
    if ocr_chars > native_chars:
        best_text = ocr_text
        source = "ocr"
        best_blocks = ocr_blocks
    else:
        best_text = native_text
        source = "pdftotext"
        best_blocks = []
    return ExtractedPdf(
        pdf_path=pdf_path,
        blocks=best_blocks,
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


def run_ocr_all_pages(pdf_path: Path, temp_dir: Path, dpi: float = 300.0) -> list[TextBlock]:
    temp_dir.mkdir(parents=True, exist_ok=True)
    page_count = get_pdf_page_count(pdf_path)
    all_blocks: list[TextBlock] = []
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
                ["tesseract", str(png_path), "stdout", "tsv", "--dpi", str(int(dpi))],
                check=True,
                capture_output=True,
                text=True,
            )
            page_blocks = parse_tsv_blocks(ocr.stdout or "", page=page_num, dpi=dpi)
            all_blocks.extend(page_blocks)
        finally:
            safe_unlink(png_path)
    return all_blocks


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
