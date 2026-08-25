# Security Policy

## Supported versions

The published `v0.2.x` line remains supported while `v0.3.0` is prepared.
Development milestones before `v0.1.0` do not receive security backports.

| Version | Supported |
| --- | --- |
| 0.3.x | Yes, once released |
| 0.2.x | Yes |
| 0.1.x | No |
| < 0.1.0 | No |

Only the latest patch in a supported minor release is expected to receive
security fixes.

## Reporting a vulnerability

GitHub private vulnerability reporting is not currently enabled for this
repository. Until a private reporting channel is available, open a minimal
[security issue](https://github.com/tonygloaguen/PySynoptic/issues/new) that
contains no exploit details, credentials, private paths, or proprietary source.
Ask the maintainers to arrange private follow-up before sharing sensitive
technical information.

Do not include source from a private or proprietary project in a public report.
A small, synthetic reproducer may be shared publicly only when it contains no
sensitive data.

Please include, when safe:

- the affected PySynoptic version and platform;
- the security boundary or operation involved;
- minimal reproduction conditions;
- the potential impact;
- whether the issue is already public.

General bugs without a security impact belong in the regular issue tracker.

## Static-analysis security boundary

PySynoptic is designed to analyze source without executing it. Analyzed project
code must never be:

- imported or loaded as a package;
- executed with Python;
- evaluated through `eval` or `exec`;
- launched through a subprocess;
- inspected through runtime module loading or introspection.

The intended analysis inputs are filesystem metadata and Python source text.
The implementation uses `ast.parse()` and static models to resolve structure
and relationships. Static Insights and deterministic FlowExplanation are
derived locally from AST-based facts and the existing static models.

A vulnerability that causes analyzed source to be imported or executed is
security-significant. So is a path-handling defect that unexpectedly reads or
writes outside the selected analysis or export boundary. Reports about these
behaviors should follow the vulnerability process above.

PySynoptic does not provide a sandbox for running untrusted code because it is
not supposed to run analyzed code at all.

## Optional AI explanation boundary

AI-enhanced explanations are an optional presentation layer over deterministic
static results. They do not change the analysis security boundary above:

- AI support is disabled by default;
- no provider call occurs automatically;
- every request requires an explicit user action;
- raw Python source is not included in provider requests;
- only a structured representation derived from static analysis is sent;
- quoted literals are redacted before the request is built;
- names, symbol identities, and inferred purposes can remain in the structured
  representation and may contain sensitive information;
- PySynoptic asks for confirmation before using a remote endpoint;
- API keys come from the current session or environment and are not persisted;
- provider requests are limited to 12,000 characters;
- returned explanation text is limited to 2,000 characters;
- network operations run outside the Tk event thread;
- provider text is labeled as AI-enhanced reformulation and never becomes
  static Evidence or a source of truth.

Users must review the structured-data privacy warning before enabling a remote
provider and must not send sensitive identifiers to a service they do not
trust. A local Ollama-compatible endpoint avoids remote transmission, but its
operation and data handling remain the responsibility of that local service.
