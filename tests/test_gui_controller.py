from pathlib import Path

import pytest

from pysynoptic.gui.controller import ApplicationController
from pysynoptic.gui.state import (
    ApplicationState,
    controls_for_state,
    mark_analysis_started,
)


def write_python(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_initial_application_state_is_empty() -> None:
    state = ApplicationState()

    assert state.selected_path is None
    assert state.target_kind is None
    assert state.file_analysis is None
    assert state.project_analysis is None
    assert state.mermaid_source == ""
    assert state.error_message is None
    assert state.is_analyzing is False


def test_analysis_pending_state_disables_mutating_controls(tmp_path: Path) -> None:
    selected = ApplicationController().select_path(tmp_path)

    pending = mark_analysis_started(selected)
    controls = controls_for_state(pending)

    assert pending.is_analyzing is True
    assert pending.status_message == f"Analyzing project: {tmp_path}"
    assert controls.can_select is False
    assert controls.can_analyze is False
    assert controls.can_export is False


def test_selects_python_file(tmp_path: Path) -> None:
    path = write_python(tmp_path / "module.py")

    state = ApplicationController().select_path(path)

    assert state.selected_path == path
    assert state.target_kind == "file"
    assert state.error_message is None


def test_selects_project_directory(tmp_path: Path) -> None:
    state = ApplicationController().select_path(tmp_path)

    assert state.selected_path == tmp_path
    assert state.target_kind == "project"


def test_rejects_invalid_selection(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("text\n", encoding="utf-8")

    state = ApplicationController().select_path(path)

    assert state.target_kind is None
    assert state.error_message is not None
    assert "Expected a .py file" in state.error_message


def test_reports_missing_selection_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.py"

    state = ApplicationController().select_path(path)

    assert state.target_kind is None
    assert state.error_message == f"Path not found: {path}"


def test_requires_selection_before_analysis() -> None:
    state = ApplicationController().analyze(ApplicationState())

    assert state.error_message == "Choose a Python file or project before analyzing."


def test_analyzes_single_file(tmp_path: Path) -> None:
    path = write_python(
        tmp_path / "module.py",
        "import os\n\ndef run():\n    pass\n",
    )
    controller = ApplicationController()

    state = controller.analyze(controller.select_path(path))

    assert state.file_analysis is not None
    assert state.file_analysis.functions == ("run",)
    assert state.file_analysis.imports == ("os",)
    assert state.project_analysis is not None
    assert len(state.project_analysis.callable_identities) == 1
    assert state.status_message == "File analysis complete."


def test_reports_single_file_syntax_error_without_crashing(tmp_path: Path) -> None:
    path = write_python(tmp_path / "broken.py", "def broken(:\n")
    controller = ApplicationController()

    state = controller.analyze(controller.select_path(path))

    assert state.file_analysis is not None
    assert state.file_analysis.syntax_error is not None
    assert state.error_message is None
    assert state.status_message == "File analysis completed with a syntax error."


def test_analyzes_project_and_prepares_all_views(tmp_path: Path) -> None:
    write_python(tmp_path / "target.py", "value = 1\n")
    write_python(tmp_path / "source.py", "import target\n")
    controller = ApplicationController()

    state = controller.analyze(controller.select_path(tmp_path))

    assert state.project_analysis is not None
    assert len(state.project_analysis.module_identities) == 2
    assert len(state.project_analysis.dependencies) == 1
    assert "flowchart LR" in state.mermaid_source
    assert "module_source -->|imports| module_target" in state.mermaid_source
    assert state.status_message == "Project analysis complete."


def test_project_analysis_never_executes_selected_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    write_python(
        tmp_path / "dangerous.py",
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
    )
    controller = ApplicationController()

    controller.analyze(controller.select_path(tmp_path))

    assert not marker.exists()


def test_exports_current_project_mermaid(tmp_path: Path) -> None:
    write_python(tmp_path / "module.py")
    controller = ApplicationController()
    state = controller.analyze(controller.select_path(tmp_path))
    output_path = tmp_path / "exports" / "dependencies.mmd"

    returned_path = controller.export_mermaid(state, output_path)

    assert returned_path == output_path
    assert output_path.read_text(encoding="utf-8") == state.mermaid_source


def test_rejects_export_without_project(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Analyze a project"):
        ApplicationController().export_mermaid(
            ApplicationState(),
            tmp_path / "dependencies.mmd",
        )


def test_new_selection_clears_previous_analysis(tmp_path: Path) -> None:
    write_python(tmp_path / "project" / "module.py")
    file_path = write_python(tmp_path / "single.py")
    controller = ApplicationController()
    analyzed = controller.analyze(controller.select_path(tmp_path / "project"))

    selected = controller.select_path(file_path)

    assert analyzed.project_analysis is not None
    assert selected.file_analysis is None
    assert selected.project_analysis is None
    assert selected.mermaid_source == ""
