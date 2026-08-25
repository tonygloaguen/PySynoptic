# Changelog

This changelog follows the principles of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
PySynoptic uses semantic versioning for public releases.

## [Unreleased]

## [0.3.0] - 2026-08-25

### Added

- deterministic FlowExplanation summaries answering “How does it work?” for
  functions and methods;
- hierarchical Key Steps covering decisions, loops, exception paths, calls,
  and outcomes;
- Key Step navigation to the corresponding highlighted Flow node;
- lazy caching of callable CFG and FlowExplanation results;
- optional AI-enhanced explanation reformulation through OpenAI-compatible and
  Ollama-compatible providers.

### Security

- AI explanations are disabled by default and require an explicit user action;
- raw Python source and quoted literals are not sent to AI providers;
- remote endpoints require confirmation, while keys remain session-only or
  environment-provided and are never persisted;
- AI requests and responses are bounded, network work stays outside the Tk
  thread, and returned prose never becomes Evidence or a source of truth;
- the existing non-execution and non-import boundary for analyzed code remains
  unchanged.

## [0.2.0] - 2026-08-24

### Added

- deterministic Static Insights for modules, classes, functions, and methods;
- conservative role classification with qualitative High, Medium, or Unknown
  confidence;
- Purpose explanations with explicit docstring, inference, or structural
  provenance;
- structured responsibilities, inputs, outputs, side effects, callers, and
  callees;
- inspectable static Evidence supporting each Insight;
- an Insights desktop view with synchronized Tree, Calls, Flow, and Insights
  navigation.

### Changed

- callable selection now remains synchronized across all code-exploration
  views.

### Security

- Static Insights preserve the static-only analysis boundary and are derived
  locally from AST facts and existing static models;
- analyzed source remains never imported, executed, or transmitted externally.

## [0.1.0] - 2026-08-24

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
