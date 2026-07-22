"""Zero-token CLI diagnostic module for checking output PDF visual annotation health."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def audit_pdf_outputs(output_dir: Path) -> dict[str, Any]:
    import fitz

    if not output_dir.exists():
        print(f"Directory not found: {output_dir}")
        return {"error": f"Directory not found: {output_dir}"}

    pdf_files = list(output_dir.glob("**/*.pdf"))
    print(f"Auditing {len(pdf_files)} output PDFs in {output_dir}...")

    oob_defects = []
    overlap_defects = []
    page_mismatch_defects = []
    header_only_scanned_count = 0

    for p in pdf_files:
        try:
            doc = fitz.open(p)
            total_text_len = sum(len(page.get_text().strip()) for page in doc)
            if 0 < total_text_len < 300:
                header_only_scanned_count += 1

            for page_num, page in enumerate(doc, start=1):
                pw, ph = page.rect.width, page.rect.height
                annots = list(page.annots() or [])
                rects: list[tuple[str, fitz.Rect]] = []

                for a in annots:
                    r = a.rect
                    subj = (a.info or {}).get("subject", "")

                    # 1. Out of Bounds Check
                    if r.x0 < 0 or r.y0 < 0 or r.x1 > pw + 1.0 or r.y1 > ph + 1.0:
                        oob_defects.append(
                            f"{p.relative_to(output_dir)} [P{page_num} {subj}]: rect=({r.x0:.1f}, {r.y0:.1f}, {r.x1:.1f}, {r.y1:.1f}) canvas=({pw:.1f}, {ph:.1f})"
                        )

                    # 2. Bounding Box Overlap Check (>30% box area intersection)
                    for prev_subj, prev_r in rects:
                        if r.intersects(prev_r):
                            intersect = r & prev_r
                            area = intersect.width * intersect.height
                            min_area = min(r.width * r.height, prev_r.width * prev_r.height)
                            if min_area > 0 and (area / min_area) > 0.30:
                                overlap_defects.append(
                                    f"{p.relative_to(output_dir)} [P{page_num}]: \"{subj}\" vs \"{prev_subj}\" ({area/min_area*100:.0f}% overlap)"
                                )
                    rects.append((subj, r))

                    # 3. Page Mismatch Check (High Q numbers placed on Page 1)
                    if subj.startswith("question_mark|"):
                        for token in subj.split("|"):
                            if token.startswith("q="):
                                qid = token[2:]
                                if qid.isdigit() and int(qid) >= 5 and page_num == 1 and len(doc) > 1:
                                    page_mismatch_defects.append(
                                        f"{p.relative_to(output_dir)}: Question {qid} placed on Page 1 of {len(doc)} pages"
                                    )
            doc.close()
        except Exception as exc:
            print(f"Error reading {p}: {exc}")

    print("\n================ Audit Summary ================")
    print(f"Total PDFs Scanned: {len(pdf_files)}")
    print(f"Scanned / Header-only PDFs: {header_only_scanned_count}")
    print(f"OOB Bleeding Defects: {len(oob_defects)}")
    print(f"Box Overlap Defects (>30%): {len(overlap_defects)}")
    print(f"Page Mismatch Warnings: {len(page_mismatch_defects)}")

    if oob_defects:
        print("\nSample OOB Defects:")
        for d in oob_defects[:5]:
            print(f"  - {d}")

    if overlap_defects:
        print("\nSample Overlap Defects:")
        for d in overlap_defects[:5]:
            print(f"  - {d}")

    return {
        "total_pdfs": len(pdf_files),
        "oob_defects": len(oob_defects),
        "overlap_defects": len(overlap_defects),
        "page_mismatches": len(page_mismatch_defects),
        "scanned_header_only": header_only_scanned_count,
    }


def main() -> int:
    path_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs")
    results = audit_pdf_outputs(path_arg)
    if results.get("oob_defects", 0) > 0 or results.get("overlap_defects", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
