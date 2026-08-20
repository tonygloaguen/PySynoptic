"""Default directory exclusions for project discovery."""

from __future__ import annotations

DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "venv",
    }
)


def is_excluded_directory(name: str) -> bool:
    """Return whether a directory name is excluded by default."""
    return name in DEFAULT_EXCLUDED_DIRECTORIES
