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
            convert_non_pdf_files_to_pdf(folder)
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


def convert_non_pdf_files_to_pdf(folder: Path) -> None:
    import fitz
    import zipfile
    import xml.etree.ElementTree as ET

    # Get non-PDF files
    all_files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    
    # Process images
    images = [p for p in all_files if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    if images:
        try:
            doc = fitz.open()
            for img_path in sorted(images, key=lambda p: p.name.lower()):
                img_doc = fitz.open(img_path)
                pdf_bytes = img_doc.convert_to_pdf()
                img_doc.close()
                doc.insert_pdf(fitz.open("pdf", pdf_bytes))
            output_path = folder / f"{folder.name}_images.pdf"
            doc.save(output_path)
            doc.close()
        except Exception:
            pass
            
    # Process DOCX
    docx_files = [p for p in all_files if p.suffix.lower() == ".docx"]
    for docx_path in docx_files:
        try:
            with zipfile.ZipFile(docx_path) as z:
                xml_content = z.read('word/document.xml')
                root = ET.fromstring(xml_content)
                text_runs = []
                for paragraph in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    para_text = []
                    for run in paragraph.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
                        if run.text:
                            para_text.append(run.text)
                    text_runs.append("".join(para_text))
                text = "\n".join(text_runs)
                
            doc = fitz.open()
            page = doc.new_page()
            y = 50
            margin = 50
            line_height = 15
            for line in text.split("\n"):
                if y > page.rect.height - 50:
                    page = doc.new_page()
                    y = 50
                max_chars = 90
                for chunk in [line[i:i+max_chars] for i in range(0, len(line), max_chars)] or [""]:
                    if y > page.rect.height - 50:
                        page = doc.new_page()
                        y = 50
                    page.insert_text((margin, y), chunk, fontsize=10, fontname="helv")
                    y += line_height
            output_path = folder / f"{docx_path.stem}.pdf"
            doc.save(output_path)
            doc.close()
        except Exception:
            pass
            
    # Process XLSX
    xlsx_files = [p for p in all_files if p.suffix.lower() == ".xlsx"]
    for xlsx_path in xlsx_files:
        try:
            with zipfile.ZipFile(xlsx_path) as z:
                shared_strings = []
                try:
                    strings_content = z.read('xl/sharedStrings.xml')
                    strings_root = ET.fromstring(strings_content)
                    for t in strings_root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'):
                        shared_strings.append(t.text or "")
                except KeyError:
                    pass

                sheet_content = z.read('xl/worksheets/sheet1.xml')
                sheet_root = ET.fromstring(sheet_content)
                
                rows = {}
                for row in sheet_root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                    row_idx = int(row.get('r'))
                    row_cells = []
                    for cell in row.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                        cell_ref = cell.get('r')
                        cell_type = cell.get('t')
                        val_el = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                        val = ""
                        if val_el is not None and val_el.text:
                            if cell_type == 's':
                                idx = int(val_el.text)
                                val = shared_strings[idx] if idx < len(shared_strings) else val_el.text
                            else:
                                val = val_el.text
                        row_cells.append((cell_ref, val))
                    row_cells.sort(key=lambda x: x[0])
                    rows[row_idx] = [val for ref, val in row_cells if val]
                    
                lines = []
                for r_idx in sorted(rows.keys()):
                    if rows[r_idx]:
                        lines.append("  |  ".join(rows[r_idx]))
                text = "\n".join(lines)
                
            doc = fitz.open()
            page = doc.new_page()
            y = 50
            margin = 50
            line_height = 15
            for line in text.split("\n"):
                if y > page.rect.height - 50:
                    page = doc.new_page()
                    y = 50
                max_chars = 90
                for chunk in [line[i:i+max_chars] for i in range(0, len(line), max_chars)] or [""]:
                    if y > page.rect.height - 50:
                        page = doc.new_page()
                        y = 50
                    page.insert_text((margin, y), chunk, fontsize=10, fontname="helv")
                    y += line_height
            output_path = folder / f"{xlsx_path.stem}.pdf"
            doc.save(output_path)
            doc.close()
        except Exception:
            pass

