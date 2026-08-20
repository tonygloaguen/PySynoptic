from pathlib import Path

import pytest

import pysynoptic.analyzer.project as project_analyzer
from pysynoptic import analyze_project
from pysynoptic.models import FileAnalysis
from pysynoptic.scanner import DEFAULT_EXCLUDED_DIRECTORIES, scan_project


def write_file(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def relative_paths(paths: tuple[Path, ...], root: Path) -> set[Path]:
    return {path.relative_to(root) for path in paths}


def test_discovers_python_files_recursively(tmp_path: Path) -> None:
    write_file(tmp_path / "root.py")
    write_file(tmp_path / "first" / "module.py")
    write_file(tmp_path / "first" / "second" / "deep.py")

    scan = scan_project(tmp_path)

    assert relative_paths(scan.python_files, tmp_path) == {
        Path("root.py"),
        Path("first/module.py"),
        Path("first/second/deep.py"),
    }


def test_discovers_nested_packages_and_special_modules(tmp_path: Path) -> None:
    write_file(tmp_path / "package" / "__init__.py")
    write_file(tmp_path / "package" / "__main__.py")
    write_file(tmp_path / "package" / "nested" / "__init__.py")

    analysis = analyze_project(tmp_path)

    assert relative_paths(analysis.python_files, tmp_path) == {
        Path("package/__init__.py"),
        Path("package/__main__.py"),
        Path("package/nested/__init__.py"),
    }
    assert len(analysis.file_analyses) == 3


def test_excludes_default_directories_from_discovery(tmp_path: Path) -> None:
    write_file(tmp_path / "visible.py", "value = 1\n")
    for directory_name in DEFAULT_EXCLUDED_DIRECTORIES:
        write_file(tmp_path / directory_name / "hidden.py", "def hidden(): pass\n")

    analysis = analyze_project(tmp_path)

    assert relative_paths(analysis.python_files, tmp_path) == {Path("visible.py")}
    assert {path.name for path in analysis.excluded_paths} == set(
        DEFAULT_EXCLUDED_DIRECTORIES
    )
    assert tuple(item.path.name for item in analysis.file_analyses) == ("visible.py",)


def test_catalogues_non_python_resources(tmp_path: Path) -> None:
    write_file(tmp_path / "assets" / "logo.png", "not image data")
    write_file(tmp_path / "config.yml", "enabled: true\n")
    write_file(tmp_path / "data.json", "{}\n")
    write_file(tmp_path / "index.html", "<main></main>\n")
    write_file(tmp_path / "README.md", "# Project\n")
    write_file(tmp_path / "page.jinja2", "{{ value }}\n")
    write_file(tmp_path / "Dockerfile", "FROM scratch\n")
    write_file(tmp_path / "archive.bin", "data")

    scan = scan_project(tmp_path)
    resources = {item.path.relative_to(tmp_path): item.kind for item in scan.resources}

    assert resources == {
        Path("archive.bin"): "other",
        Path("assets/logo.png"): "image",
        Path("config.yml"): "configuration",
        Path("data.json"): "data",
        Path("Dockerfile"): "configuration",
        Path("index.html"): "web",
        Path("page.jinja2"): "template",
        Path("README.md"): "documentation",
    }


def test_analyzes_empty_project(tmp_path: Path) -> None:
    analysis = analyze_project(tmp_path)

    assert analysis.root_path == tmp_path
    assert analysis.python_files == ()
    assert analysis.resources == ()
    assert analysis.excluded_paths == ()
    assert analysis.file_analyses == ()
    assert analysis.errors == ()


def test_keeps_syntax_error_on_relevant_file(tmp_path: Path) -> None:
    invalid_path = write_file(tmp_path / "broken.py", "def broken(:\n    pass\n")

    analysis = analyze_project(tmp_path)

    assert analysis.errors == ()
    assert analysis.file_analyses[0].path == invalid_path
    assert analysis.file_analyses[0].syntax_error is not None


def test_continues_after_invalid_python_file(tmp_path: Path) -> None:
    valid_path = write_file(tmp_path / "valid.py", "def available():\n    pass\n")
    invalid_path = write_file(tmp_path / "broken.py", "class Broken(\n")

    analysis = analyze_project(tmp_path)
    analyses = {item.path: item for item in analysis.file_analyses}

    assert analyses[valid_path].functions == ("available",)
    assert analyses[valid_path].syntax_error is None
    assert analyses[invalid_path].syntax_error is not None


def test_reports_read_error_and_continues(tmp_path: Path) -> None:
    unreadable_path = tmp_path / "invalid_encoding.py"
    unreadable_path.write_bytes(b"\xff\xfe")
    valid_path = write_file(tmp_path / "valid.py", "class Available:\n    pass\n")

    analysis = analyze_project(tmp_path)

    assert tuple(item.path for item in analysis.file_analyses) == (valid_path,)
    assert len(analysis.errors) == 1
    assert analysis.errors[0].path == unreadable_path
    assert analysis.errors[0].operation == "read"


def test_rejects_nonexistent_project_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Project path not found"):
        analyze_project(tmp_path / "missing")


def test_rejects_path_that_is_not_a_directory(tmp_path: Path) -> None:
    file_path = write_file(tmp_path / "notes.txt", "text\n")

    with pytest.raises(NotADirectoryError, match="Expected a project directory"):
        analyze_project(file_path)


def test_files_inside_excluded_directories_are_never_analyzed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    visible_path = write_file(tmp_path / "visible.py", "value = 1\n")
    write_file(tmp_path / ".venv" / "hidden.py", "value = 2\n")
    analyzed_paths: list[Path] = []

    def record_analysis(path: Path) -> FileAnalysis:
        analyzed_paths.append(path)
        return FileAnalysis(path=path, module_name=path.stem)

    monkeypatch.setattr(project_analyzer, "analyze_python_file", record_analysis)

    analyze_project(tmp_path)

    assert analyzed_paths == [visible_path]


def test_project_analysis_never_executes_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    write_file(
        tmp_path / "dangerous.py",
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
    )

    analyze_project(tmp_path)

    assert not marker.exists()
