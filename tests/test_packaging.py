import tomllib
from pathlib import Path

from pysynoptic import __version__

PROJECT_ROOT = Path(__file__).parents[1]


def test_pyinstaller_version_is_pinned_for_reproducible_builds() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["project"]["optional-dependencies"]["package"] == [
        "pyinstaller==6.22.2"
    ]


def test_spec_builds_windowed_onedir_from_existing_gui_launcher() -> None:
    spec = (PROJECT_ROOT / "packaging" / "pysynoptic.spec").read_text(encoding="utf-8")

    assert '"src" / "pysynoptic" / "gui" / "__main__.py"' in spec
    assert "application = COLLECT(" in spec
    assert 'hiddenimports=["PIL._tkinter_finder"]' in spec
    assert "console=False" in spec
    assert "upx=False" in spec
    assert "onefile" not in spec.casefold()


def test_package_workflow_targets_windows_and_linux_onedir_artifacts() -> None:
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "package.yml").read_text(
        encoding="utf-8"
    )

    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "packaging/pysynoptic.spec" in workflow
    assert "xvfb-run" in workflow
    assert "Start-Process" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert 'archive="PySynoptic-v${version}-' in workflow
    assert __version__ == "0.0.11"
