from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from pathlib import Path

from typing import Any
from .types import ExtractedPdf, TextBlock


def compute_optimal_dpi(pdf_path: Path, target_max_dim: float = 2048.0, default_dpi: float = 150.0) -> float:
    """Dynamically compute an optimal DPI to avoid rendering massive images for scanned PDFs."""
    try:
        result = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("page size:"):
                # e.g. "Page size:      612 x 792 pts (letter)"
                parts = line.split(":", 1)[1].strip().split()
                if len(parts) >= 3 and parts[1] == "x":
                    try:
                        width = float(parts[0])
                        height = float(parts[2])
                        max_dim_pts = max(width, height)
                        if max_dim_pts > 0:
                            computed_dpi = target_max_dim * 72.0 / max_dim_pts
                            return min(computed_dpi, default_dpi)
                    except ValueError:
                        pass
                break
    except Exception:
        pass
    return default_dpi


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
            scale = 72.0 / dpi
            left = float(parts[6]) * scale
            top = float(parts[7]) * scale
            width = float(parts[8]) * scale
            height = float(parts[9]) * scale
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


GEMINI_FALLBACK_CONF_THRESHOLD = 60.0


def extract_pdf_text(
    pdf_path: Path,
    temp_dir: Path,
    ocr_char_threshold: int = 200,
    gemini_api_key: str | None = None,
    gemini_model: str = "gemini-3.1-flash-lite",
    rate_limiter: Any | None = None,
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

    # Fall back to Gemini Flash if tesseract yielded nothing or low confidence.
    if _needs_gemini_fallback(ocr_blocks) and gemini_api_key:
        ocr_blocks = _run_gemini_fallback(
            pdf_path=pdf_path,
            temp_dir=temp_dir,
            api_key=gemini_api_key,
            model=gemini_model,
            rate_limiter=rate_limiter,
        )

    ocr_text = "\n".join(b.text for b in ocr_blocks)
    ocr_chars = non_whitespace_char_count(ocr_text)
    if ocr_chars > native_chars:
        best_text = ocr_text
        source = "gemini_flash" if ocr_blocks and ocr_blocks[0].source == "gemini_flash" else "ocr"
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


def _needs_gemini_fallback(blocks: list[TextBlock]) -> bool:
    if not blocks:
        return True
    confident = [b for b in blocks if b.confidence >= 0]
    if not confident:
        return False
    mean_conf = sum(b.confidence for b in confident) / len(confident)
    return mean_conf < GEMINI_FALLBACK_CONF_THRESHOLD


def _run_gemini_fallback(
    pdf_path: Path,
    temp_dir: Path,
    api_key: str,
    model: str,
    dpi: float | None = None,
    rate_limiter: Any | None = None,
) -> list[TextBlock]:
    from .ocr_gemini import extract_blocks_gemini

    if dpi is None:
        dpi = compute_optimal_dpi(pdf_path, target_max_dim=2048.0, default_dpi=150.0)

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
                "-f", str(page_num),
                "-l", str(page_num),
                "-singlefile",
                "-r", str(int(dpi)),
                "-png",
                str(pdf_path),
                str(out_prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            page_blocks = extract_blocks_gemini(
                image_path=png_path,
                page=page_num,
                api_key=api_key,
                model=model,
                dpi=dpi,
                rate_limiter=rate_limiter,
            )
            all_blocks.extend(page_blocks)
        finally:
            safe_unlink(png_path)
    return all_blocks


def run_pdftotext(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    # pdftotext may emit syntax warnings on stderr but still return useful text.
    return result.stdout or ""


def run_ocr_all_pages(pdf_path: Path, temp_dir: Path, dpi: float | None = None) -> list[TextBlock]:
    if dpi is None:
        dpi = compute_optimal_dpi(pdf_path, target_max_dim=2048.0, default_dpi=150.0)
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
                "-r",
                str(int(dpi)),
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
