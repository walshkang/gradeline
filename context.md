# Gradeline — Current Context

## Next up

- **Web Review App Custom Bands Support** — update `grader/review/static/app.js` and HTML view to support dynamic numeric bands editing instead of hardcoded `check_plus_min` / `check_min` fields.

---

## Recent work

- **Rate Limiter & Concurrency Auto-Clamping** — Added thread-safe sliding window RPM and daily RPD limit enforcement via `RateLimiterRegistry` ([rate_limit.py](file:///Users/walsh.kang/Documents/GitHub/gradeline/grader/rate_limit.py)). Auto-clamps execution workers to fit within API free-tier RPM limits.
- **Checkpoint / Resume grading runs** — Added run configuration hashing and file-based state serialization ([checkpoint.py](file:///Users/walsh.kang/Documents/GitHub/gradeline/grader/checkpoint.py)). Gradeline gracefully checkpoints progress upon a `DailyLimitExhausted` exception or a `KeyboardInterrupt` stop, resuming cleanly on subsequent runs via `--resume` or the TUI `resume` menu item.
- **No-Fallback Pithy Feedback Policy** — Eradicated boilerplate and static fallback strings when the AI fails to produce correct second-person reasons, opting to print clean `x Q{id}` marks with empty text comments to "air on the side of caution".
- **Custom Dynamic Grading Bands** — Removed hardcoded `Check Plus`/`Check`/`Check Minus` validation in rubric parsing. Grading now evaluates arbitrary bands (like `10, 9, 8, 7, 6, 5`) dynamically by sorted threshold order and assigns numeric band names directly to CSV points.
- **Performance & Tests** — Added comprehensive unit test coverage for rate limits and checkpoints (`161 passed`).

## Branch

`main` — all work lands directly on main.
