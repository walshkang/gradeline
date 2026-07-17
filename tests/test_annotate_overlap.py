import fitz
from grader.annotate import insert_mark

def test_insert_mark_collision_mitigation():
    doc = fitz.open()
    page = doc.new_page()
    point = fitz.Point(100, 100)
    
    placed_rects = {}
    
    # Place 5 annotations at the same point
    for i in range(5):
        insert_mark(
            page=page,
            point=point,
            mark_text=f"x Q1.{i}: some reason text",
            is_correct=False,
            question_id=f"1.{i}",
            fontsize=12.0,
            placed_rects=placed_rects,
        )
        
    annots = list(page.annots())
    assert len(annots) == 5
    
    # Assert all resulting rects are non-overlapping
    rects = [annot.rect for annot in annots]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not rects[i].intersects(rects[j]), f"Rect {i} and {j} overlap: {rects[i]} vs {rects[j]}"


def test_nudge_downward_and_rightward():
    doc = fitz.open()
    page = doc.new_page()
    point = fitz.Point(100, 100)
    placed_rects = {}
    
    # First annotation
    insert_mark(
        page=page,
        point=point,
        mark_text="first mark",
        is_correct=True,
        question_id="1",
        fontsize=12.0,
        placed_rects=placed_rects,
    )
    
    # Second annotation at the same point
    insert_mark(
        page=page,
        point=point,
        mark_text="second mark",
        is_correct=True,
        question_id="2",
        fontsize=12.0,
        placed_rects=placed_rects,
    )
    
    annots = list(page.annots())
    assert len(annots) == 2
    r1, r2 = annots[0].rect, annots[1].rect
    
    # Second rect should be shifted downward
    assert r2.y0 >= r1.y1, f"Second rect y0 ({r2.y0}) should be below first rect y1 ({r1.y1})"
