# Security Policy

## Supported versions

The published `v0.1.x` line remains supported while `v0.2.0` is prepared.
Development milestones before `v0.1.0` do not receive security backports.

| Version | Supported |
| --- | --- |
| 0.2.x | Yes, once released |
| 0.1.x | Yes |
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
and relationships. Static Insights are derived locally from AST-based facts and
the existing static models; analyzed source is not transmitted externally.

A vulnerability that causes analyzed source to be imported or executed is
security-significant. So is a path-handling defect that unexpectedly reads or
writes outside the selected analysis or export boundary. Reports about these
behaviors should follow the vulnerability process above.

PySynoptic does not provide a sandbox for running untrusted code because it is
not supposed to run analyzed code at all.
