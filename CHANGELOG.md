# Changelog

This changelog follows the principles of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
PySynoptic uses semantic versioning for public releases.

## [Unreleased]

## [0.1.0] - TBD

### Added

- static analysis for standalone Python files and complete project trees;
- stable module identity and conservative internal dependency resolution;
- focused, interactive Architecture exploration with dependency-cycle details;
- callable inventory with lexical and source identities;
- conservative resolved, ambiguous, unresolved, and dynamic call
  classification;
- contextual Calls exploration with incoming, outgoing, and bidirectional
  depth controls;
- structural per-callable Flow exploration for branches, loops, exception
  handling, calls, and terminating statements;
- deterministic Mermaid export for project and current graphical views;
- responsive desktop analysis with stale-result protection;
- native PyInstaller `onedir` packaging for Windows x64 and Linux x64;
- continuous integration on Python 3.11, 3.12, 3.13, and 3.14.

### Security

- analyzed Python source is read as text and parsed statically;
- analyzed projects are never imported or executed;
- the analyzer uses filesystem metadata, AST, and static models only.

### Known limitations

- dynamic Python behavior prevents complete static call resolution;
- generic receiver calls, inheritance, and type inference are intentionally
  unsupported;
- control-flow graphs are structural rather than compiler-perfect;
- global graphs may remain dense on very large projects;
- Windows bundles are unsigned, Linux compatibility depends on the build
  environment, and no macOS bundle is provided yet.
