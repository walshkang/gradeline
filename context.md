# Gradeline — Current Context

## Next up

**TUI + agent-friendly CLI** — see [`docs/plans/tui-agent-improvements.md`](docs/plans/tui-agent-improvements.md)

Four slices. Wave 1 is fully parallelizable (no shared files):

| Slice | What | Agent level | Wave |
|---|---|---|---|
| A — Exit codes | New codes 3/4 in `conclude()`, fix 4 review-server gates in `workflow_cli.py`, update tests | Sonnet | 1 |
| B — Progress bar | `MofNCompleteColumn` + `TimeRemainingColumn` + rolling tally in `ui.py` | Haiku | 1 |
| C — `CLAUDE.md` | Repo-root project instructions for AI assistant sessions | Haiku | 1 |
| D — `--json` + `--quiet` | `QuietConsoleUI`, JSON summary to stdout, env var support | Sonnet | 2 (after A) |

---

## Recent work

- **Bounding box annotation pipeline** — Tesseract TSV → `TextBlock` block registry → XML-wrapped blocks in grading prompt → `block_id` lookup for spatial annotation placement. Fallback chain: `block_id` → `model_coords` → `local_anchor` → `summary_fallback`. See `grader/extract.py`, `grader/ocr_gemini.py`, `grader/annotate.py`.
- **Grading pipeline fixes** — CASCADING ERROR RULE and TOLERANCE RULE added to system prompt; `assignment4.yaml` rubric updated with explicit tolerance ranges. See `grader/gemini_client.py`.
- **Performance** — `concurrency = 8` global default in `configs/defaults.toml`; `extract_blocks = false` profile flag to skip OCR for all-handwritten assignments; `FIRST_COMPLETED` event loop fix that eliminated end-of-run hang.
- **Docs** — `README.md` How It Works section, `docs/runbook.md`.

## Branch

`main` — all work lands directly on main.
