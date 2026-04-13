"""Gemini Flash vision fallback for OCR extraction with bounding boxes.

Used when tesseract yields too few characters (e.g. messy handwriting).
Returns TextBlock objects in the same format as the tesseract TSV path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .types import TextBlock

OCR_EXTRACTION_PROMPT = """\
You are an OCR extraction engine. Extract all readable text from this page image.

Return a JSON array. Each element represents one logical text block (a paragraph, \
heading, or isolated line). Use this schema:

[
  {
    "block_num": 1,
    "text": "the full text of this block",
    "left": 120,
    "top": 450,
    "width": 280,
    "height": 30
  }
]

Rules:
- Coordinates are in pixels relative to the top-left corner of the image.
- Group words that form a sentence or paragraph into one block.
- Preserve original spelling and numbers exactly — do not correct errors.
- If no text is found, return an empty array: []
- Return only the JSON array, no explanation.
"""


def extract_blocks_gemini(
    image_path: Path,
    page: int,
    api_key: str,
    model: str = "gemini-2.0-flash",
    dpi: float = 216.0,
) -> list[TextBlock]:
    """Send a rasterized page image to Gemini Flash and parse TextBlock objects."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    image_bytes = image_path.read_bytes()
    image_part = genai_types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/png",
    )

    response = client.models.generate_content(
        model=model,
        contents=[image_part, OCR_EXTRACTION_PROMPT],
        config={"response_mime_type": "application/json"},
    )

    text = _response_text(response)
    raw_blocks = _parse_json_array(text)
    return _to_text_blocks(raw_blocks, page=page, dpi=dpi)


def _response_text(response: Any) -> str:
    try:
        return response.text or ""
    except Exception:
        try:
            return response.candidates[0].content.parts[0].text or ""
        except Exception:
            return ""


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    # Strip markdown fences if present
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []


def _to_text_blocks(
    raw: list[dict[str, Any]],
    page: int,
    dpi: float,
) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for item in raw:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        block_num = item.get("block_num", len(blocks) + 1)
        blocks.append(
            TextBlock(
                id=f"p{page}_b{block_num}",
                text=text,
                page=page,
                left=float(item.get("left", 0)),
                top=float(item.get("top", 0)),
                width=float(item.get("width", 0)),
                height=float(item.get("height", 0)),
                source="gemini_flash",
                confidence=-1.0,
            )
        )
    return blocks
