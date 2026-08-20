# PySynoptic

PySynoptic is an open-source static analysis tool for exploring the structure of
Python source code. Its long-term goal is to turn a file or a project into a
clear, navigable synopsis of modules, declarations, and their relationships.

## Static analysis only

PySynoptic **never executes or imports analyzed code**. The current engine reads
the selected source file as text and passes it to Python's `ast.parse()` parser.
This principle is a core project invariant, including for future project-wide
analysis.

## Current capabilities

Version `0.1.0` analyzes one `.py` file and reports:

- the file path and inferred module name;
- top-level synchronous and asynchronous functions;
- top-level classes;
- top-level `import x` and `from x import y` statements;
- syntax errors with their source location.

It rejects missing files and files whose extension is not `.py`. It does not yet
resolve calls, nested declarations, imported objects, or relationships between
modules.

## Developer installation

Python 3.11 or newer is required. From a clone of the repository:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the quality checks with:

```bash
pytest
ruff check .
ruff format --check .
```

## CLI usage

After installation, analyze a file with either entry point:

```bash
pysynoptic path/to/module.py
python -m pysynoptic path/to/module.py
```

Example output:

```text
File: path/to/module.py
Module: module
Functions: main, load_config
Classes: Application
Imports: argparse, pathlib.Path
```

The analysis engine is also available independently of the CLI:

```python
from pathlib import Path

from pysynoptic import analyze_python_file

analysis = analyze_python_file(Path("path/to/module.py"))
```

## Short roadmap

1. Analyze complete package and project trees.
2. Model module-to-module dependencies and function calls.
3. Export stable machine-readable analysis results.
4. Build an interactive visualization layer on top of the independent engine.

## License

PySynoptic is distributed under the MIT License. See [`LICENSE`](LICENSE).
