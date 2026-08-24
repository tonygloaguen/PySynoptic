# Contributing to PySynoptic

Thank you for helping make Python code easier to understand. Contributions are
welcome when they preserve PySynoptic's deterministic static-analysis model.

## Prerequisites

- Python 3.11 or newer
- Git
- a graphical desktop for manual GUI checks

## Development setup

```bash
git clone https://github.com/tonygloaguen/PySynoptic.git
cd PySynoptic
python -m venv .venv
```

Activate the environment and install the project:

```bash
# Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the GUI with `pysynoptic-gui` and the CLI with `pysynoptic --help`.

## Quality checks

Run all checks before opening a pull request:

```bash
pytest
ruff check .
ruff format --check .
python -m compileall src
git diff --check
```

Continuous integration runs the test and quality suite on Python 3.11, 3.12,
3.13, and 3.14.

## Branch and pull-request workflow

Create a focused branch from an up-to-date `main`:

- `feature/*` for functionality;
- `fix/*` for corrections;
- `docs/*` for documentation;
- `build/*` for packaging or build infrastructure.

Pull requests target `main`. Keep commits and PRs focused, describe observable
behavior and limitations, and wait for the complete CI matrix. Do not include
private analyzed source, local build output, credentials, or unrelated files.

## Architecture rules

PySynoptic keeps responsibilities deliberately separate:

- `scanner` discovers files and resources;
- `analyzer` interprets source and resolves static relationships;
- `models` represent immutable analysis results;
- `graph` builds logical graphs and deterministic layouts;
- `renderers` export completed models and logical graphs;
- `gui` presents results and coordinates interaction.

The GUI must not duplicate AST analysis. Graph and renderer layers must not
inspect the runtime import system to fill gaps in static evidence.

Most importantly, **analyzed code must never be imported or executed**. Do not
use `importlib`, runtime package loading, `inspect` on analyzed modules, `eval`,
`exec`, subprocess execution, or runtime introspection of an analyzed project.
This rule is mandatory for every contribution.

## Tests

New behavior and bug fixes should include tests. Prefer small, deterministic
fixtures that prove both positive and conservative-negative cases. Static
analysis changes should test ambiguity, shadowing, and unsupported dynamic
behavior where relevant.

Keep GUI business logic headless-testable where possible. Widget-level manual
checks complement automated tests but do not replace model, builder,
controller, and helper tests.

If a change affects the visual interface, include a concise manual smoke-test
description in the pull request. Packaging changes should be validated on each
native target because PyInstaller is not a cross-compiler.

## Reporting security issues

Follow [SECURITY.md](SECURITY.md). Never attach private or proprietary analyzed
source to a public issue.
