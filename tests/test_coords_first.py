import fitz
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from grader.types import TextBlock, ExtractedPdf, QuestionResult, RubricConfig
from grader.gemini_schemas import build_context_system_instruction
from grader.location_resolver import resolve_model_location


def test_build_context_system_instruction_coords_first_clarification():
    rubric = RubricConfig(assignment_id="test", questions=[], bands=None)
    system_inst = build_context_system_instruction(rubric)
    assert "If no <answer> blocks are provided in the prompt, you MUST set coords=[y,x] for each question." in system_inst


def test_resolve_model_location_rejects_megablock():
    doc = fitz.open()
    # Create 100x100 page (area = 10000)
    doc.new_page(width=100.0, height=100.0)

    # Mega-block: area = 4000 (>30% of 10000)
    mega_block = TextBlock(
        id="p1_b1",
        text="handwritten answer page",
        page=1,
        left=10.0,
        top=10.0,
        width=80.0,
        height=50.0,
        source="ocr",
    )
    block_registry = {"p1_b1": mega_block}

    result = QuestionResult(
        id="1",
        logic_analysis="",
        verdict="correct",
        confidence=1.0,
        short_reason="",
        detail_reason="",
        evidence_quote="",
        block_id="p1_b1",
        coords=[500, 500],
        page_number=1,
    )

    # When resolve_model_location is called, the mega-block (>30% page area) should be rejected,
    # and placement should fall back to coords [500, 500].
    loc = resolve_model_location(
        doc=doc,
        pdf_filename="test.pdf",
        result=result,
        block_registry=block_registry,
    )

    assert loc is not None
    # 3-tuple returned when resolved via coords (vs 4-tuple for block_id)
    assert len(loc) == 3
    page_idx, point, norm_coords = loc
    assert page_idx == 0
    assert norm_coords == (500.0, 500.0)

    doc.close()


def test_resolve_model_location_accepts_normal_block():
    doc = fitz.open()
    # Create 1000x1000 page (area = 1,000,000)
    doc.new_page(width=1000.0, height=1000.0)

    # Normal block: area = 10,000 (1% of 1,000,000)
    normal_block = TextBlock(
        id="p1_b1",
        text="Q1 Answer",
        page=1,
        left=50.0,
        top=100.0,
        width=100.0,
        height=100.0,
        source="ocr",
    )
    block_registry = {"p1_b1": normal_block}

    result = QuestionResult(
        id="1",
        logic_analysis="",
        verdict="correct",
        confidence=1.0,
        short_reason="",
        detail_reason="",
        evidence_quote="",
        block_id="p1_b1",
        coords=[100, 100],
        page_number=1,
    )

    loc = resolve_model_location(
        doc=doc,
        pdf_filename="test.pdf",
        result=result,
        block_registry=block_registry,
    )

    assert loc is not None
    page_idx, point, norm_coords, placement_source = loc
    assert page_idx == 0
    assert placement_source == "block_id"

    doc.close()
