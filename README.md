# PySynoptic

PySynoptic is an open-source static analysis tool for exploring the structure of
Python source code. Its long-term goal is to turn a file or a project into a
clear, navigable synopsis of modules, declarations, and their relationships.

## Static analysis only

PySynoptic **never executes or imports analyzed code**. Project discovery only
inspects the filesystem. The analysis engine reads each selected Python source
file as text and passes it to Python's `ast.parse()` parser. It does not use
`importlib`, evaluate source expressions, or start subprocesses from an analyzed
project.

## Current capabilities

Version `0.0.5` analyzes either one `.py` file or a complete directory tree. It
reports:

- the file path and inferred module name;
- top-level synchronous and asynchronous functions;
- top-level classes;
- structured `import x` and `from x import y` metadata from every lexical
  scope, including aliases, relative levels, and source positions;
- syntax errors with their source location;
- recursively discovered Python files, including package entry points;
- stable project-aware dotted module identities;
- resolved, external, unresolved, ambiguous, and namespace import references;
- deterministic, deduplicated dependencies between file-backed modules;
- deterministic Mermaid flowcharts generated directly from project analyses;
- non-Python project resources grouped by broad type;
- excluded paths and recoverable filesystem or source-reading errors.

Common generated, environment, dependency, and cache directories such as
`.git`, `.venv`, `__pycache__`, `node_modules`, `build`, and `dist` are excluded
without being traversed. One invalid or unreadable Python file does not prevent
the remaining project from being analyzed.

For module identities, PySynoptic recognizes the conventional `src/` layout as
well as flat projects. A project `src/` directory is treated as the most
specific source root, while the project root remains available for top-level
scripts. Namespace-style package directories do not require `__init__.py`.

Import resolution only compares AST metadata with the discovered project module
identities. It never inspects the runtime environment, installed packages, or
the import system.

Imports inside functions, classes, branches, loops, context managers,
`try`/`except`/`finally`, `match` cases, and `TYPE_CHECKING` blocks are all
recorded. PySynoptic does not predict whether a branch executes; every import
present in the static syntax tree contributes to the analysis.

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
python -m compileall src
```

## CLI usage

After installation, analyze a file or a project directory with either entry
point:

```bash
pysynoptic path/to/module.py
python -m pysynoptic path/to/module.py
pysynoptic path/to/project
pysynoptic path/to/project --format mermaid
pysynoptic path/to/project --format mermaid --output dependencies.mmd
```

Example output:

```text
File: path/to/module.py
Module: module
Functions: main, load_config
Classes: Application
Imports: argparse, pathlib.Path
```

Project output starts with a concise summary and then lists every discovered
Python file:

```text
Project: example
Python files: 3
Resources: 2
Functions: 5
Classes: 1
Syntax errors: 0
Dependencies: 2

Files:
- package
  package/__init__.py
- package.__main__
  package/__main__.py
- package.service
  package/service.py

Dependencies:
- package -> package.service
- package.__main__ -> package.service
```

The analysis engine is also available independently of the CLI:

```python
from pathlib import Path

from pysynoptic import analyze_project, analyze_python_file, render_mermaid

file_analysis = analyze_python_file(Path("path/to/module.py"))
project_analysis = analyze_project(Path("path/to/project"))
mermaid = render_mermaid(project_analysis)
```

The scanner is a separate layer from Python AST analysis: it inventories files
and resources but never parses source itself. Module identity resolution is a
separate project-analysis step and does not modify the single-file analyzer's
stem-based `module_name`. Project-level import resolution consumes structured
AST metadata and emits a logical dependency graph as immutable Python data.
The Mermaid renderer consumes only this completed `ProjectAnalysis`; it never
reads or imports analyzed source code.

## Generated architecture diagram

PySynoptic generates its own dependency diagram at
[`docs/pysynoptic-dependencies.mmd`](docs/pysynoptic-dependencies.mmd). Nodes
are grouped by their top-level package, and both nodes and edges are emitted in
a stable order suitable for version control and exact-string testing.

## Current limitations

- declarations nested inside functions or classes are not catalogued;
- dynamic imports and calls to `__import__` are not interpreted;
- external versus unresolved classification is based only on known project
  top-level names;
- fileless namespace packages do not produce dependency edges themselves;
- function calls are not resolved;
- Mermaid output currently supports module dependencies only;
- resources are catalogued but not linked to Python code;
- symbolic links are excluded rather than followed;
- source roots configured through packaging metadata are not yet interpreted;
- only the conventional top-level `src/` directory is detected specially.

## Short roadmap

1. Add JSON export for file and project analyses.
2. Model function and method calls on top of the stable module graph.
3. Add graph filtering and visual styles for dependency categories.
4. Build an interactive visualization layer on top of the independent engine.

## License

PySynoptic is distributed under the MIT License. See [`LICENSE`](LICENSE).
