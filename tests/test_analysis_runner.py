from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident

import pytest

from pysynoptic.gui.analysis_runner import AnalysisRunner
from pysynoptic.gui.controller import ApplicationController
from pysynoptic.gui.state import ApplicationState


def selected_state(name: str = "project") -> ApplicationState:
    return ApplicationState(
        selected_path=Path(f"/{name}"),
        target_kind="project",
        status_message=f"Project selected: /{name}",
    )


def wait_for_result(runner: AnalysisRunner) -> ApplicationState:
    pause = Event()
    for _ in range(5000):
        result = runner.poll_latest()
        if result is not None:
            return result
        pause.wait(0.001)
    pytest.fail("background analysis did not produce a result")


def wait_until_idle(runner: AnalysisRunner) -> None:
    pause = Event()
    for _ in range(5000):
        if runner.active_count == 0:
            return
        pause.wait(0.001)
    pytest.fail("background analysis did not stop")


def test_submits_analysis_on_a_background_thread() -> None:
    started = Event()
    release = Event()
    worker_identifiers: list[int] = []

    def analyze(state: ApplicationState) -> ApplicationState:
        worker_identifiers.append(get_ident())
        started.set()
        release.wait()
        return replace(state, status_message="complete")

    runner = AnalysisRunner(analyze)
    request_id = runner.submit(selected_state())

    assert started.wait(5)
    assert request_id == 1
    assert runner.active_count == 1
    assert runner.poll_latest() is None
    assert worker_identifiers != [get_ident()]

    release.set()
    assert wait_for_result(runner).status_message == "complete"
    runner.shutdown(wait=True)


def test_returns_success_state_with_pending_flag_cleared() -> None:
    runner = AnalysisRunner(
        lambda state: replace(
            state,
            is_analyzing=True,
            status_message="Project analysis complete.",
        )
    )

    runner.submit(selected_state())
    completed = wait_for_result(runner)

    assert completed.status_message == "Project analysis complete."
    assert completed.is_analyzing is False
    assert completed.error_message is None
    runner.shutdown(wait=True)


def test_converts_unexpected_worker_failure_to_error_state() -> None:
    def fail(_state: ApplicationState) -> ApplicationState:
        raise RuntimeError("worker failed")

    runner = AnalysisRunner(fail)

    runner.submit(selected_state())
    completed = wait_for_result(runner)

    assert completed.is_analyzing is False
    assert completed.status_message == "Analysis failed: worker failed"
    assert completed.error_message == "Analysis failed: worker failed"
    runner.shutdown(wait=True)


def test_stale_result_cannot_replace_newer_request() -> None:
    releases = {"old": Event(), "new": Event()}
    started = {"old": Event(), "new": Event()}

    def analyze(state: ApplicationState) -> ApplicationState:
        name = state.selected_path.name
        started[name].set()
        releases[name].wait()
        return replace(state, status_message=f"complete: {name}")

    runner = AnalysisRunner(analyze)
    runner.submit(selected_state("old"))
    assert started["old"].wait(5)
    runner.submit(selected_state("new"))
    assert started["new"].wait(5)

    releases["old"].set()
    wait_until_idle_or_active_request(runner, expected_active=1)
    assert runner.poll_latest() is None

    releases["new"].set()
    completed = wait_for_result(runner)
    assert completed.selected_path == Path("/new")
    assert completed.status_message == "complete: new"
    runner.shutdown(wait=True)


def wait_until_idle_or_active_request(
    runner: AnalysisRunner,
    *,
    expected_active: int,
) -> None:
    pause = Event()
    for _ in range(5000):
        if runner.active_count == expected_active:
            return
        pause.wait(0.001)
    pytest.fail("background request did not reach expected state")


def test_repeated_analysis_returns_each_current_generation() -> None:
    call_count = 0

    def analyze(state: ApplicationState) -> ApplicationState:
        nonlocal call_count
        call_count += 1
        return replace(state, status_message=f"complete {call_count}")

    runner = AnalysisRunner(analyze)

    runner.submit(selected_state())
    assert wait_for_result(runner).status_message == "complete 1"
    runner.submit(selected_state())
    assert wait_for_result(runner).status_message == "complete 2"
    assert call_count == 2
    runner.shutdown(wait=True)


def test_invalidation_discards_in_flight_result() -> None:
    started = Event()
    release = Event()

    def analyze(state: ApplicationState) -> ApplicationState:
        started.set()
        release.wait()
        return state

    runner = AnalysisRunner(analyze)
    runner.submit(selected_state())
    assert started.wait(5)

    invalidating_generation = runner.invalidate()
    release.set()
    wait_until_idle(runner)

    assert invalidating_generation == 2
    assert runner.poll_latest() is None
    runner.shutdown(wait=True)


def test_shutdown_rejects_new_work_and_ignores_completion() -> None:
    started = Event()
    release = Event()

    def analyze(state: ApplicationState) -> ApplicationState:
        started.set()
        release.wait()
        return state

    runner = AnalysisRunner(analyze)
    runner.submit(selected_state())
    assert started.wait(5)

    runner.shutdown()
    release.set()
    wait_until_idle(runner)

    assert runner.closed is True
    assert runner.poll_latest() is None
    with pytest.raises(RuntimeError, match="closed"):
        runner.submit(selected_state())


def test_analyzes_large_synthetic_project_asynchronously(tmp_path: Path) -> None:
    package = tmp_path / "synthetic"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    for index in range(64):
        previous_import = (
            ""
            if index == 0
            else f"from synthetic.module_{index - 1} import entry as previous\n"
        )
        previous_call = "return None" if index == 0 else "return previous()"
        source = (
            f"{previous_import}\n"
            "def helper():\n"
            f"    {previous_call}\n\n"
            "class Service:\n"
            "    def run(self):\n"
            "        return helper()\n\n"
            "def entry():\n"
            "    return helper()\n"
        )
        (package / f"module_{index}.py").write_text(source, encoding="utf-8")

    controller = ApplicationController()
    runner = AnalysisRunner(controller.analyze)
    request_id = runner.submit(controller.select_path(tmp_path))
    completed = wait_for_result(runner)

    assert request_id == 1
    assert completed.project_analysis is not None
    assert len(completed.project_analysis.module_identities) == 65
    assert len(completed.project_analysis.dependencies) == 63
    assert len(completed.project_analysis.callable_identities) == 192
    assert len(completed.project_analysis.call_resolutions) == 191
    assert len(completed.project_analysis.call_dependencies) == 191
    assert completed.status_message == "Project analysis complete."
    runner.shutdown(wait=True)
