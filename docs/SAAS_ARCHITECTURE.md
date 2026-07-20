# Creator Transformation SaaS Architecture

## Product boundary

The first public release is a long-form transformation studio for authors,
publishers, podcast producers, and course creators. Rather than forcing every
source through one localization pipeline, each project stores one explicit
workflow type: audio transcription, audio translation, translated audio, book
translation, or audiobook creation.

The studio exposes 34 source and target languages, including automatic source
detection where the selected workflow permits it. The quality program should
still begin with a smaller tested matrix—especially Serbian, Croatian, Bosnian,
English, German, Spanish, and French—before every combination is marketed as
production-proven.

The differentiator is the adaptive production workflow: source validation,
transcription or manuscript segmentation, glossary-controlled translation,
conditional voice authorization, narration, and private artifact delivery. It
is not positioned as a generic text translator or as performance-preserving
voice conversion.

## Deployment shape

```text
React web application
        |
        v
Flask API -------------- PostgreSQL
   |                         |
   |                         +-- users, organizations, memberships
   |                         +-- projects, jobs, subscriptions, usage ledger
   |
   +-- Object storage (S3/R2)
   |       +-- source audio/manuscripts, previews, MP3s, JSON artifacts
   |
   +-- Redis queue
           |
           v
       Worker processes
           +-- transcription provider
           +-- translation provider
           +-- voice provider
           +-- FFmpeg post-production
```

Local development uses SQLite, local file storage, and an in-process worker
fallback. Production must use PostgreSQL, object storage, and Redis-backed
workers so that uploads and jobs survive restarts.

## Core domain objects

- `User`: identity, password hash, verification and account status.
- `Organization`: billing and ownership boundary.
- `Membership`: user role within an organization.
- `Project`: one source work, creator-selected workflow, and language settings.
- `Artifact`: source, transcript, translation, preview, export, and report files.
- `PipelineJob`: persistent state and progress for a processing operation.
- `UsageEvent`: immutable credit/minute ledger entry.
- `Subscription`: billing-provider state mirrored from signed webhooks.
- `VoiceConsent`: auditable confirmation that a speaker authorized voice use.

## Processing and metering

Billable usage is measured in source-processing minutes. Workflows without
target languages count one output; multilingual workflows count every target:

```text
rounded source minutes x max(1, number of generated target languages)
```

Every debit or credit is an immutable usage event with an idempotency key.
Subscriptions grant monthly credits; one-time credit packs use the same ledger.
No processing job may start unless sufficient available credit is reserved.
Failed jobs release their reservation.

## Security and trust defaults

- Platform API keys remain server-side. Bring-your-own-key is an enterprise
  feature and requires encrypted secret storage.
- Uploaded files use random object keys, never user-provided paths.
- Downloads use short-lived signed URLs or authenticated local routes.
- Passwords are hashed using Werkzeug's current secure password hasher.
- Public deployments require non-default session and admin secrets.
- Workflows that generate voice require a stored rights declaration and
  voice-consent record; text-only workflows do not request irrelevant consent.
- Generated audio records provider/model provenance and AI-content disclosure.
- Raw source retention defaults to 30 days and can be shortened by the customer.

## Delivery phases

1. **Complete:** stabilize the existing MVP, add tests, configuration validation,
   and CI.
2. **Complete:** add authentication, organizations, projects, persistent jobs,
   and storage.
3. **Complete:** generalize the pipeline for multiple languages and model
   routing.
4. **Complete:** add credit accounting and Lemon Squeezy subscription
   synchronization.
5. **Complete:** replace the single-screen prototype with a public site and
   project studio.
6. **Complete:** add creator-selected book/audio workflows, document ingestion,
   conditional voice gates, and workflow-aware metering.
7. **Next:** deploy an invite-only private beta, measure unit economics and
   quality, close the launch checklist, then open access.

## Production gates

- Passing backend and frontend builds.
- No in-memory-only authoritative state.
- Per-job isolated files and idempotent retries.
- Signed and replay-safe billing webhooks.
- Upload size/type validation and malware scanning hook.
- Rate limiting, structured logs, error tracking, backups, and deletion jobs.
- Terms, privacy policy, acceptable-use policy, refund policy, and voice-consent
  language reviewed for the launch jurisdictions.
