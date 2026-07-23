from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import fitz
    from .types import QuestionResult, RubricConfig


@dataclass
class AnnotationSession:
    """Encapsulates tracking state during student PDF annotation pipeline execution."""

    placed_rects: dict[int, list[fitz.Rect]] = field(default_factory=dict)
    rendered: set[str] = field(default_factory=set)
    rendered_subparts: set[str] = field(default_factory=set)
    placement_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_paths: list[Path] = field(default_factory=list)
    result_map: dict[str, QuestionResult] = field(default_factory=dict)

    def clear_placed_rects(self) -> None:
        self.placed_rects.clear()

    def mark_rendered(self, question_id: str) -> None:
        self.rendered.add(question_id)

    def is_rendered(self, question_id: str) -> bool:
        return question_id in self.rendered

    def mark_subpart_rendered(self, subpart_key: str) -> None:
        self.rendered_subparts.add(subpart_key)

    def is_subpart_rendered(self, subpart_key: str) -> bool:
        return subpart_key in self.rendered_subparts

    def record_placement(self, question_id: str, details: dict[str, Any]) -> None:
        self.placement_details[question_id] = details

    def finalize_updated_results(
        self, question_results: list[QuestionResult]
    ) -> list[QuestionResult]:
        updated_results: list[QuestionResult] = []
        for result in question_results:
            details = self.placement_details.get(result.id)
            if details is None:
                updated_results.append(result)
                continue
            coords_value = details.get("coords")
            coords = coords_value if isinstance(coords_value, tuple) else None
            page_number = details.get("page_number")
            source_file = details.get("source_file")
            placement_source = details.get("placement_source")
            updated_results.append(
                replace(
                    result,
                    coords=coords if coords is not None else result.coords,
                    page_number=page_number if isinstance(page_number, int) else result.page_number,
                    source_file=source_file if isinstance(source_file, str) else result.source_file,
                    placement_source=placement_source if isinstance(placement_source, str) else result.placement_source,
                )
            )
        return updated_results
