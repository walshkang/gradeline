import queue
import threading
import json
from typing import Any, Dict, Optional, Generator
from ..ui import ConsoleUI, RunSummary
from ..orchestrator import Orchestrator
from ..workflow.profile_utils import build_grading_config

class SSEProgressUI(ConsoleUI):
    def __init__(self, event_queue: queue.Queue):
        self.q = event_queue
        self.submissions_total = 0
        self.submissions_completed = 0
        self.current_folder = ""

    def _push_event(self, event_type: str, data: Dict[str, Any]) -> None:
        try:
            self.q.put({"event": event_type, "data": data}, block=False)
        except queue.Full:
            pass

    def banner(self, title: str, subtitle: str = "") -> None:
        self.info(f"{title} - {subtitle}")

    def info(self, message: str) -> None:
        self._push_event("info", {"message": message})

    def warning(self, message: str) -> None:
        self._push_event("warning", {"message": message})

    def error(self, message: str) -> None:
        self._push_event("error", {"message": message})

    def submission_started(self, index: int, total: int, folder_name: str) -> None:
        self.current_folder = folder_name
        self.submissions_total = total
        self._push_event("progress", {
            "index": index,
            "total": total,
            "folder_name": folder_name,
            "status": "started"
        })

    def submission_finished(
        self,
        index: int,
        total: int,
        folder_name: str,
        *,
        band: str,
        had_error: bool,
        rationale: str = "",
        elapsed_seconds: float = 0.0,
        snapshot: Any = None,
    ) -> None:
        self.submissions_completed += 1
        self._push_event("progress", {
            "index": index,
            "total": total,
            "folder_name": folder_name,
            "status": "finished",
            "band": band,
            "had_error": had_error,
            "rationale": rationale,
            "elapsed_seconds": elapsed_seconds,
            "band_counts": snapshot.band_counts if snapshot else {}
        })

    def emit_artifacts(self, artifacts: dict) -> None:
        pass

    def emit_summary(self, summary: RunSummary) -> None:
        pass

    def status(self, message: str) -> None:
        self._push_event("status", {"message": message, "folder_name": self.current_folder})

    def clear_status(self) -> None:
        pass

    def start_progress(self, total: int) -> None:
        self.submissions_total = total
        self._push_event("progress_start", {"total": total})

    def advance_progress(self) -> None:
        pass

    def stop_progress(self) -> None:
        pass

    def section_heading(self, title: str) -> None:
        pass

    def add_submission_task(self, folder_name: str, total_questions: int) -> int:
        return 0

    def update_submission_task(self, task_id: int, current: int, question_id: str) -> None:
        pass

    def remove_submission_task(self, task_id: int) -> None:
        pass


class GradingSessionManager:
    def __init__(self):
        self.state = "idle"
        self.thread: Optional[threading.Thread] = None
        self.q: queue.Queue = queue.Queue(maxsize=1000)
        self.profile = ""
        self.orchestrator: Optional[Orchestrator] = None

    def start_grading(self, profile: str) -> None:
        if self.state == "running":
            raise ValueError("A grading session is already running.")

        self.profile = profile
        self.state = "running"
        # Clear queue
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

        self.thread = threading.Thread(target=self._run_grading_thread, args=(profile,))
        self.thread.daemon = True
        self.thread.start()

    def cancel(self) -> None:
        if self.state == "running":
            self.state = "cancelled"
            try:
                self.q.put({"event": "info", "data": {"message": "Cancelling grading session..."}}, block=False)
            except queue.Full:
                pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "profile": self.profile,
        }

    def _run_grading_thread(self, profile: str) -> None:
        try:
            ui = SSEProgressUI(self.q)
            try:
                from ..workflow_profile import load_workflow_profile
                from ..workflow_cli import build_grading_argv, get_project_root
                from ..cli import main as cli_main

                profile_data = load_workflow_profile(profile, cwd=get_project_root())
                grading_argv = build_grading_argv(profile_data.grade)
                
                # cli_main returns exit code; we run it synchronously in this background thread
                exit_code = cli_main(grading_argv, ui_override=ui)
                
                if exit_code == 0:
                    self.q.put({"event": "complete", "data": {"message": "Grading run finished successfully."}})
                    self.state = "completed"
                else:
                    self.q.put({"event": "error", "data": {"message": f"Grading run failed with exit code {exit_code}."}})
                    self.state = "failed"
            except Exception as e:
                ui.error(f"Grading failed: {e}")
                self.q.put({"event": "error", "data": {"message": str(e)}})
                self.state = "failed"
        finally:
            if self.state == "running":
                self.state = "completed"

    def events_generator(self) -> Generator[bytes, None, None]:
        # Yields SSE strings
        while self.state == "running" or not self.q.empty():
            try:
                event_dict = self.q.get(timeout=1.0)
                event_type = event_dict.get("event", "message")
                data_json = json.dumps(event_dict.get("data", {}))
                yield f"event: {event_type}\ndata: {data_json}\n\n".encode("utf-8")
            except queue.Empty:
                if self.state != "running":
                    break
        
        yield b"event: close\ndata: {}\n\n"
