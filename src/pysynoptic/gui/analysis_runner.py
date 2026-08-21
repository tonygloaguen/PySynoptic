"""Headless-safe background coordination for GUI analysis requests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from queue import Empty, SimpleQueue
from threading import Lock, Thread, current_thread

from pysynoptic.gui.state import ApplicationState


@dataclass(frozen=True, slots=True)
class AnalysisCompletion:
    """One completed background analysis associated with its generation."""

    request_id: int
    state: ApplicationState


class AnalysisRunner:
    """Run analysis on daemon threads and expose only the newest completion."""

    def __init__(
        self,
        analyze: Callable[[ApplicationState], ApplicationState],
    ) -> None:
        self._analyze = analyze
        self._lock = Lock()
        self._completions: SimpleQueue[AnalysisCompletion] = SimpleQueue()
        self._threads: set[Thread] = set()
        self._latest_request_id = 0
        self._closed = False

    @property
    def latest_request_id(self) -> int:
        """Return the newest submitted or invalidating generation."""
        with self._lock:
            return self._latest_request_id

    @property
    def active_count(self) -> int:
        """Return the number of analysis threads still running."""
        with self._lock:
            return len(self._threads)

    @property
    def closed(self) -> bool:
        """Return whether shutdown has rejected further work."""
        with self._lock:
            return self._closed

    def submit(self, state: ApplicationState) -> int:
        """Submit an analysis request and immediately return its generation."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Analysis runner is closed")
            self._latest_request_id += 1
            request_id = self._latest_request_id
            thread = Thread(
                target=self._run,
                args=(request_id, state),
                name=f"pysynoptic-analysis-{request_id}",
                daemon=True,
            )
            self._threads.add(thread)
        thread.start()
        return request_id

    def invalidate(self) -> int:
        """Make every currently submitted result stale without blocking."""
        with self._lock:
            if self._closed:
                return self._latest_request_id
            self._latest_request_id += 1
            return self._latest_request_id

    def poll_latest(self) -> ApplicationState | None:
        """Drain completed work and return only the current generation."""
        with self._lock:
            if self._closed:
                return None
            latest_request_id = self._latest_request_id
        latest_state: ApplicationState | None = None
        while True:
            try:
                completion = self._completions.get_nowait()
            except Empty:
                break
            if completion.request_id == latest_request_id:
                latest_state = completion.state
        return latest_state

    def shutdown(self, *, wait: bool = False) -> None:
        """Reject new work and optionally join already running daemon threads."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._latest_request_id += 1
            threads = tuple(self._threads)
        if wait:
            for thread in threads:
                thread.join()
        while True:
            try:
                self._completions.get_nowait()
            except Empty:
                break

    def _run(self, request_id: int, state: ApplicationState) -> None:
        try:
            completed = self._analyze(state)
        except Exception as error:
            message = f"Analysis failed: {error}"
            completed = replace(
                state,
                is_analyzing=False,
                status_message=message,
                error_message=message,
            )
        else:
            completed = replace(completed, is_analyzing=False)
        finally:
            with self._lock:
                self._threads.discard(current_thread())

        with self._lock:
            closed = self._closed
        if not closed:
            self._completions.put(AnalysisCompletion(request_id, completed))
