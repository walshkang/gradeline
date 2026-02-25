from __future__ import annotations

import html
import re
from pathlib import Path

from .types import JsonDict, SubmissionUnit


def discover_submission_units(submissions_dir: Path) -> list[SubmissionUnit]:
    units: list[SubmissionUnit] = []
    for folder in sorted([p for p in submissions_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        pdfs = sorted(folder.rglob("*.pdf"), key=lambda p: str(p.relative_to(folder)).lower())
        if not pdfs:
            continue
        token, student_name = parse_folder_name(folder.name)
        units.append(
            SubmissionUnit(
                folder_path=folder,
                folder_relpath=folder.relative_to(submissions_dir),
                folder_token=token,
                student_name=student_name,
                pdf_paths=pdfs,
            )
        )
    return units


def parse_folder_name(name: str) -> tuple[str, str]:
    parts = [segment.strip() for segment in name.split(" - ")]
    token = parts[0] if parts else name
    student_name = parts[1] if len(parts) > 1 else name
    return token, student_name


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def parse_index_html(index_html_path: Path) -> list[JsonDict]:
    if not index_html_path.exists():
        return []
    text = index_html_path.read_text(encoding="utf-8", errors="ignore")
    # Brightspace export often stores one "header row + file rows" sequence.
    name_matches = list(re.finditer(r"<b>([^<]+,\s*[^<]+)</b>", text, flags=re.IGNORECASE))
    entries: list[JsonDict] = []
    for idx, match in enumerate(name_matches):
        person = html.unescape(match.group(1)).strip()
        start = match.end()
        end = name_matches[idx + 1].start() if idx + 1 < len(name_matches) else len(text)
        chunk = text[start:end]

        for file_match in re.finditer(
            r"valign=top>([^<]+?)<p[^>]*><b>Comments:</b><br>(.*?)</td><td valign=top><b>Submitted:</b><br>([^<]+)</td>",
            chunk,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            filename = html.unescape(file_match.group(1)).strip()
            comments_html = file_match.group(2)
            submitted = html.unescape(file_match.group(3)).strip()
            comments = _html_to_text(comments_html)
            entries.append(
                {
                    "student_name": person,
                    "submitted_filename": filename,
                    "submitted_at": submitted,
                    "comments": comments,
                }
            )
    return entries


def _html_to_text(raw: str) -> str:
    scrubbed = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    scrubbed = re.sub(r"<[^>]+>", "", scrubbed)
    return html.unescape(scrubbed).strip()

