from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RasterMeta:
    page_width_pt: float
    page_height_pt: float
    image_width_px: int
    image_height_px: int
    scale: float
    etag: str


@dataclass
class RasterImage:
    meta: RasterMeta
    png_bytes: bytes


class RasterImageCache:
    def __init__(self, max_entries: int = 128) -> None:
        self.max_entries = max(4, int(max_entries))
        self._cache: OrderedDict[str, RasterImage] = OrderedDict()

    def get_page_image(
        self,
        *,
        submission_id: str,
        pdf_path: Path,
        doc_idx: int,
        page_idx: int,
        scale: float,
    ) -> RasterImage:
        file_token = fingerprint_path(pdf_path)
        key = cache_key(
            submission_id=submission_id,
            pdf_path=pdf_path,
            doc_idx=doc_idx,
            page_idx=page_idx,
            scale=scale,
            file_token=file_token,
        )
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        rendered = render_page_png(pdf_path=pdf_path, page_idx=page_idx, scale=scale)
        self._cache[key] = rendered
        self._cache.move_to_end(key)

        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return rendered


def clamp_scale(value: float | None) -> float:
    if value is None:
        return 1.2
    return max(0.5, min(3.0, float(value)))


def parse_scale(value: str | None) -> float:
    if value is None or not value.strip():
        return 1.2
    try:
        parsed = float(value)
    except ValueError:
        return 1.2
    return clamp_scale(parsed)


def cache_key(
    *,
    submission_id: str,
    pdf_path: Path,
    doc_idx: int,
    page_idx: int,
    scale: float,
    file_token: str,
) -> str:
    seed = "|".join(
        [
            submission_id,
            str(pdf_path),
            str(doc_idx),
            str(page_idx),
            f"{scale:.3f}",
            file_token,
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()  # noqa: S324


def fingerprint_path(pdf_path: Path) -> str:
    stat = pdf_path.stat()
    raw = f"{pdf_path}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324


def render_page_png(*, pdf_path: Path, page_idx: int, scale: float) -> RasterImage:
    import fitz  # Lazy import for testability.

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with fitz.open(pdf_path) as doc:
        if len(doc) == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")
        if page_idx < 0 or page_idx >= len(doc):
            raise IndexError(f"page_idx out of range: {page_idx} for {pdf_path}")

        page = doc[page_idx]
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        png_bytes = pix.tobytes("png")
        etag_seed = hashlib.sha1(png_bytes).hexdigest()  # noqa: S324
        meta = RasterMeta(
            page_width_pt=float(page.rect.width),
            page_height_pt=float(page.rect.height),
            image_width_px=int(pix.width),
            image_height_px=int(pix.height),
            scale=scale,
            etag=f'"{etag_seed}"',
        )
        return RasterImage(meta=meta, png_bytes=png_bytes)
