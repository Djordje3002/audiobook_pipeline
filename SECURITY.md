# Security policy

## Reporting a vulnerability

Do not open a public issue for authentication, authorization, billing, webhook,
file-upload, organization-isolation, secret-handling, or remote-code-execution
vulnerabilities.

Report them privately through
[GitHub Security Advisories](https://github.com/Djordje3002/audiobook_pipeline/security/advisories/new).
Include:

- The affected route, component, or revision.
- Reproduction steps using synthetic data.
- Expected and actual behavior.
- Potential impact and any suggested mitigation.

Avoid accessing, changing, or downloading data that does not belong to you. Do
not include real credentials, customer recordings, transcripts, or personal data
in the report.

## Supported versions

Security fixes are applied to the current `main` branch during private beta.
There are no supported tagged releases yet.

## Scope note

This repository implements baseline application protections, but it has not been
independently audited and does not claim formal compliance certification. Review
the public launch checklist before operating it as an unrestricted public
service.
