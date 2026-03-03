from __future__ import annotations

import re
from typing import Callable


class StreamProgressParser:
    """Incrementally parse streamed JSON text and detect per-question progress.

    This class is provider-agnostic and works purely on text. It assumes the
    model returns a JSON object shaped like UnifiedSubmissionResponse, i.e.:

        {
          "student_submission_id": "...",
          "questions": [
            {"id": "a", ...},
            {"id": "b", ...}
          ],
          "global_flags": [...]
        }

    As text chunks arrive, feed them via `feed(chunk)`. The parser maintains
    an internal buffer and scans for new `"id": "..."` occurrences that appear
    after the `"questions"` array key. When a new question id is detected for
    the first time, the optional `on_question` callback is invoked with a
    1-based index and the raw question id string.
    """

    def __init__(
        self,
        on_question: Callable[[int, str], None] | None = None,
    ) -> None:
        self._buffer: str = ""
        self._last_scan_pos: int = 0
        self._seen_ids: set[str] = set()
        self._on_question = on_question
        # Precompile a simple `"id": "value"` pattern.
        self._id_pattern = re.compile(r'"id"\s*:\s*"([^"]+)"')

    @property
    def text(self) -> str:
        """Return the full accumulated buffer."""
        return self._buffer

    def get_buffer(self) -> str:
        """Alias for `text` for clarity at call sites."""
        return self._buffer

    def feed(self, chunk: str) -> None:
        """Ingest a new text chunk and scan for question ids."""
        if not chunk:
            return

        self._buffer += chunk

        # Do not attempt to detect question ids until we have seen the
        # `"questions"` key at least once in the accumulated buffer.
        questions_idx = self._buffer.find('"questions"')
        if questions_idx == -1:
            # Nothing to scan yet, but we keep the buffer growing so that when
            # `"questions"` does appear we have the full context.
            self._last_scan_pos = len(self._buffer)
            return

        # Start scanning from the later of (last_scan_pos, first questions idx)
        # so we never rescan earlier content and also never emit ids that
        # appear before the questions array.
        start = max(self._last_scan_pos, questions_idx)
        if start >= len(self._buffer):
            return

        for match in self._id_pattern.finditer(self._buffer, start):
            qid = match.group(1)
            if qid in self._seen_ids:
                continue
            self._seen_ids.add(qid)
            if self._on_question is not None:
                index = len(self._seen_ids)
                try:
                    self._on_question(index, qid)
                except Exception:
                    # Swallow UI/observer errors so they do not affect grading.
                    pass

        self._last_scan_pos = len(self._buffer)

