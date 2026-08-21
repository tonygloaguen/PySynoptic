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

Version `0.0.10` provides both the established command-line interface and an
interactive desktop interface. It analyzes either one `.py` file or a complete
directory tree and reports:

- the file path and inferred module name;
- top-level synchronous and asynchronous functions;
- top-level classes;
- stable identities for functions, methods, and nested callable declarations;
- unresolved call references with lexical scope, source position, and raw
  name, attribute, or dynamic-expression metadata;
- conservative resolved, ambiguous, unresolved, and dynamic call results;
- deterministic callable dependencies derived only from confidently resolved
  calls;
- contextual, interactive call graphs bounded by root, direction, and depth;
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
navigate native interactive module and contextual call graphs, inspect a
summary and resolved module dependencies, view the generated Mermaid source,
and export it as an `.mmd` file. GUI orchestration remains separate from the
scanner, analyzer, models, layout, and Canvas renderer.

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

## Conservative call resolution

PySynoptic records syntax such as `run()`, `service.run()`, and
`registry[key]()` and attributes each expression to its module, class body, or
enclosing callable. Project analysis classifies every reference as:

- **resolved** when exactly one callable is supported by the static models;
- **ambiguous** when multiple callable declarations remain plausible;
- **unresolved** when the syntax is static but available evidence is
  insufficient or a name is shadowed;
- **dynamic** when the callee itself is a runtime expression.

High-confidence resolution currently covers module functions, lexical nested
functions, same-module async callables, explicitly imported callables and
aliases, imported module aliases and dotted module calls, and same-class
`self.method()` or `cls.method()` references. Duplicate definitions are
reported as ambiguous. Function arguments and obvious assignments suppress
outer-name resolution rather than producing a speculative target.

Generic `obj.method()` calls, inherited methods, computed callees such as
`registry[key]()`, runtime-generated attributes, type inference, and nontrivial
data flow are intentionally unsupported. PySynoptic does not claim complete
Python call-graph accuracy.

Call resolution preserves the static-analysis security boundary. It reads
source as text and consumes AST and immutable analysis models only. It never
loads analyzed packages, executes their imports, calls `importlib` or `inspect`
on them, evaluates expressions, runs `eval` or `exec`, starts subprocesses, or
performs runtime introspection.

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

## Desktop packaging

PySynoptic uses PyInstaller `onedir` bundles for its first desktop release.
Install the pinned packaging tool and build from the repository root:

```bash
python -m pip install -e ".[package]"
python -m PyInstaller --noconfirm --clean packaging/pysynoptic.spec
```

The unpacked application is written to `dist/PySynoptic/`. The same spec is
executed independently on Windows x64 and Linux x64 because PyInstaller output
is platform-specific. GitHub Actions smoke-tests each native GUI before
creating versioned archives such as `PySynoptic-v0.0.10-Windows-x64.zip` and
`PySynoptic-v0.0.10-Linux-x64.tar.gz`. After the release version bump, those
names become `PySynoptic-v0.1.0-*` without changing the workflow.

The bundle is windowed, keeps dependencies in an `_internal` directory, and
does not use `onefile`, UPX, an installer, or an auto-update mechanism. No icon
or platform signing is configured yet.

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
and the **Overview**, **Graph**, **Call Graph**, **Dependencies**, and
**Mermaid** tabs. **Export Mermaid** becomes available after a project
analysis.

Analysis runs on a background daemon worker so filesystem scanning, AST parsing,
import resolution, and conservative call resolution do not block Tk's event
loop. While work is pending, project-selection, analysis, and export controls
are disabled, the status bar identifies the active target, and the notebook
remains responsive. Only the newest submitted generation may update the GUI;
late results from an earlier selection are discarded.

In the **Graph** tab, drag an empty area to pan, use the mouse wheel or `+` and
`−` controls to zoom, and select **Fit** to restore the complete view. Selecting
a node emphasizes both incoming and outgoing dependencies while muting the
rest of the graph. Selecting a Python module in the project tree opens the
graph, selects the matching node, and centers it in the viewport.

The **Call Graph** tab deliberately displays a bounded context instead of the
complete project's call-reference set. Search for a module or a fully qualified
callable, choose **Outgoing**, **Incoming**, or **Both**, then select a depth of
one, two, or three relationships. Changing either control rebuilds the pure
logical subgraph before passing it through the same layout and Canvas used by
the module graph. Double-click a visible callable to make it the new root.

The diagnostics panel distinguishes the number of visible nodes and edges from
the selected root's direct incoming and outgoing dependencies. It also reports
resolved, ambiguous, unresolved, and dynamic references attributed to that
root. A module root groups its module-level references and all declared
callables in the module; a callable root focuses on one declaration.

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
controller coordinates the existing public APIs. A headless-safe background
runner invokes that controller on daemon threads and returns immutable states
through a generation-tagged queue; Tk polls the queue with `after()` and remains
the only thread that touches widgets. A deterministic pure-Python layout
condenses strongly connected components, layers the resulting DAG, and
positions any logical graph. Module dependencies and contextual call
dependencies have separate pure builders but share that layout. The native Tk
Canvas consumes only positioned values and owns viewport transforms, drawing,
selection, and activation. Tk widgets remain responsible only for file dialogs
and presenting completed state.

## Generated architecture diagram

PySynoptic generates its own dependency diagram at
[`docs/pysynoptic-dependencies.mmd`](docs/pysynoptic-dependencies.mmd). Nodes
are grouped by their top-level package, and both nodes and edges are emitted in
a stable order suitable for version control and exact-string testing.

## Current limitations

- nested non-callable declarations are not catalogued;
- dynamic imports and calls to `__import__` are not interpreted;
- external versus unresolved classification is based only on known project
  top-level names;
- fileless namespace packages do not produce dependency edges themselves;
- call resolution does not infer inheritance, receiver types, re-exports, or
  nontrivial data flow;
- a same-scope assignment conservatively blocks name resolution without
  attempting statement-order analysis;
- lambdas and other anonymous callable expressions do not receive symbol
  identities;
- call-graph navigation shows only conservative resolved dependencies and does
  not visualize unresolved or dynamic expressions as speculative edges;
- module roots can still produce a wide context in modules that declare many
  callables;
- Mermaid output currently supports module dependencies only;
- building the project tree and initial module layout still occurs on the GUI
  thread after analysis, so presenting an exceptionally large completed result
  can cause a short pause;
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
- `0.0.8`: callable identities and unresolved static call references.
- `0.0.9`: static call resolution.
- `0.0.10`: interactive function call graph.
- `0.1.0`: first public release.

## License

PySynoptic is distributed under the MIT License. See [`LICENSE`](LICENSE).
