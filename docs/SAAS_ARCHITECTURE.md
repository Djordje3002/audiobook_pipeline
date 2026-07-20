# Audiobook Localization SaaS Architecture

## Product boundary

The first public release is a long-form audio localization studio for authors,
publishers, podcast producers, and course creators. It exposes a catalog of 34
source and target languages, including automatic source-language detection. The
quality program should still begin with a smaller tested matrix—especially
Serbian, Croatian, Bosnian, English, German, Spanish, and French—before every
combination is marketed as production-proven.

The differentiator is the complete production workflow: transcription,
glossary-controlled translation, human review, voice consent, narration,
mastering, and export. It is not positioned as a generic text translator.

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
   |       +-- source audio, previews, exports, JSON artifacts
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
- `Project`: one source work and its localization settings.
- `Artifact`: source, transcript, translation, preview, export, and report files.
- `PipelineJob`: persistent state and progress for a processing operation.
- `UsageEvent`: immutable credit/minute ledger entry.
- `Subscription`: billing-provider state mirrored from signed webhooks.
- `VoiceConsent`: auditable confirmation that a speaker authorized voice use.

## Processing and metering

Billable usage is measured in target-processing seconds:

```text
source duration seconds x number of generated target languages
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
- Voice generation requires a stored rights declaration and voice-consent record.
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
6. **Next:** deploy an invite-only private beta, measure unit economics and
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
