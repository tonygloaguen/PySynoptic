"""Desktop GUI entry point for PySynoptic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pysynoptic.gui.app import PySynopticApp

__all__ = ["PySynopticApp", "main"]


def main() -> None:
    """Load and launch the desktop widget layer."""
    from pysynoptic.gui.app import main as run

    run()


def __getattr__(name: str) -> Any:
    if name == "PySynopticApp":
        from pysynoptic.gui.app import PySynopticApp

        return PySynopticApp
    raise AttributeError(name)
