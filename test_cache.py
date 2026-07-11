import os
from pathlib import Path
from grader.config import load_rubric
from grader.gemini_client import GeminiGrader, compute_context_cache_key

rubric = load_rubric(Path("configs/hw1.yaml"))
solutions_pdf = Path("/Users/walsh.kang/Downloads/HW1 6-8 Solutions Summer 26.pdf")
grader = GeminiGrader(
    api_key=os.environ.get("GEMINI_API_KEY", ""),
    model="gemini-2.5-flash",
    cache_dir=Path(".grader_cache")
)
context_key = compute_context_cache_key(
    model=grader.model,
    rubric=rubric,
    solutions_pdf_path=solutions_pdf,
)
print("Context key:", context_key)
# We will manually do what _resolve_context_cache does, but without the try/except
from grader.gemini_client import build_context_system_instruction, call_with_backoff
file_ref = grader._upload_and_wait(solutions_pdf)
print("File ref:", file_ref.name)
ttl = 86400
system_instruction = build_context_system_instruction(rubric)

def create_cache():
    return grader.client.caches.create(
        model=grader.model,
        config={
            "display_name": f"sda-solutions-{context_key[:12]}",
            "ttl": f"{ttl}s",
            "contents": [file_ref],
            "system_instruction": system_instruction,
        },
    )

try:
    cache = call_with_backoff(create_cache, max_retries=1)
    print("Cache created successfully:", cache.name)
except Exception as e:
    import traceback
    traceback.print_exc()
