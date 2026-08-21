# PySynoptic

[![CI](https://github.com/tonygloaguen/PySynoptic/actions/workflows/ci.yml/badge.svg)](https://github.com/tonygloaguen/PySynoptic/actions/workflows/ci.yml)

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

Version `0.0.7` provides both the established command-line interface and an
interactive desktop interface. It analyzes either one `.py` file or a complete
directory tree and reports:

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

The desktop application lets the user select a Python file or project, start
the same static analysis used by the CLI, browse the discovered project tree,
navigate a native interactive dependency graph, inspect a summary and resolved
module dependencies, view the generated Mermaid source, and export it as an
`.mmd` file. GUI orchestration remains separate from the scanner, analyzer,
models, layout, and Canvas renderer.

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

## Desktop application

Launch the interface through its dedicated entry point:

```bash
pysynoptic-gui
```

or directly as a Python module:

```bash
python -m pysynoptic.gui
```

Use **Open Python File** for a single source file or **Open Project** for a
directory, then select **Analyze**. Project analyses populate the project tree
and the **Overview**, **Graph**, **Dependencies**, and **Mermaid** tabs.
**Export Mermaid** becomes available after a project analysis.

In the **Graph** tab, drag an empty area to pan, use the mouse wheel or `+` and
`−` controls to zoom, and select **Fit** to restore the complete view. Selecting
a node emphasizes both incoming and outgoing dependencies while muting the
rest of the graph. Selecting a Python module in the project tree opens the
graph, selects the matching node, and centers it in the viewport.

The desktop layer uses `ttkbootstrap` for native Tk widgets and styling. It
delegates all analysis and rendering to the existing public engine APIs; it
does not execute or import selected source code.

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

The desktop layer follows the same boundary. Its immutable application state
contains the selected target and completed analysis values, while a small
controller coordinates the existing public APIs. A deterministic pure-Python
layout condenses strongly connected components, layers the resulting DAG, and
positions every module. The native Tk Canvas consumes only those positioned
values and owns viewport transforms, drawing, and selection. Tk widgets remain
responsible only for file dialogs and presenting completed state.

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
- analysis runs synchronously in the desktop application, so very large
  projects can temporarily block the interface;
- the dependency layout is optimized for small and medium projects and does
  not yet provide filtering or package collapsing;
- Mermaid is displayed and exported as source text, without an embedded visual
  preview;
- resources are catalogued but not linked to Python code;
- symbolic links are excluded rather than followed;
- source roots configured through packaging metadata are not yet interpreted;
- only the conventional top-level `src/` directory is detected specially.

## Short roadmap

- `0.0.1`: single-file static analysis.
- `0.0.2`: recursive project analysis.
- `0.0.3`: project-aware module identities.
- `0.0.4`: static import resolution.
- `0.0.5`: deterministic Mermaid export.
- `0.0.6`: first usable desktop GUI.
- `0.0.7`: navigable graphical preview.
- `0.0.8`: function inventory and call graph.
- `0.0.9`: interface polish and packaging.
- `0.1.0`: first public release.

## License

PySynoptic is distributed under the MIT License. See [`LICENSE`](LICENSE).
