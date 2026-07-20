# Public launch checklist

The application is a strong private-beta foundation. Do not open unrestricted
public registration until every launch gate below has an owner and is complete.

## Product and brand

- [ ] Select a final product name after trademark, company-name, social-handle,
  and domain clearance in launch markets.
- [ ] Replace the working name, placeholder support email, favicon, and domain.
- [ ] Test the full workflow with real authors/publishers in at least five source
  and five target languages.
- [ ] Measure transcription/translation quality, job failure rate, processing
  time, support burden, and gross margin.
- [ ] Re-price plans from measured provider and infrastructure costs.
- [ ] Decide whether public v1 sells translation packages only or includes
  synthetic narration. The landing page must match the enabled output exactly.

## Account lifecycle

- [ ] Add verified-email registration through a transactional email provider.
- [ ] Add time-limited, one-use password reset tokens.
- [ ] Add account, organization, project, and source-file deletion flows.
- [ ] Add organization invitations and role management before advertising team
  collaboration.
- [ ] Add support/admin tooling with separate authorization and audit logs.
- [ ] Add abuse controls for disposable email, scripted signups, and repeated free
  credit claims.

## Security and privacy

- [ ] Threat-model uploads, authenticated downloads, billing, job workers,
  provider callbacks, and organization isolation.
- [ ] Add MIME/content inspection, archive rejection, malware scanning, and upload
  quarantine. Extension checks alone are not sufficient for public uploads.
- [x] Add baseline CSP, HSTS, Referrer-Policy, Permissions-Policy, framing, and
  MIME-sniffing headers at the application layer. Revisit CSP when adding new
  third-party scripts or analytics.
- [ ] Run dependency, secret, static-analysis, and container/image scans in CI.
- [ ] Add audit logs for sign-in, membership, deletion, consent, and billing
  actions.
- [ ] Implement and test retention/deletion jobs for source audio, transcripts,
  generated files, database records, backups, and provider-held data.
- [ ] Document subprocessors, international data transfers, encryption, incident
  response, breach notification, and data-subject request handling.
- [ ] Obtain independent security review before claiming enterprise-grade
  security or compliance.

## AI and voice safety

- [ ] Have counsel review the rights declaration and narrator consent language in
  each launch jurisdiction.
- [ ] Implement stronger identity/consent evidence before voice cloning, plus
  revocation, dispute, and takedown processes.
- [ ] Add clear AI-generated-content disclosure and output provenance when audio
  generation is enabled.
- [ ] Prohibit impersonation, fraud, political deception, sexual abuse material,
  harassment, and unlicensed copyrighted use in the acceptable-use policy.
- [ ] Add human review/escalation for abuse reports and high-risk jobs.
- [ ] Review obligations under the EU AI Act and other applicable rules with
  counsel before serving affected markets.

## Billing and customer operations

- [ ] Confirm Lemon Squeezy account approval, payout support, store tax settings,
  plan variants, receipt branding, refund rules, and live-mode webhook delivery.
- [ ] Decide how upgrades, downgrades, cancellations, refunds, chargebacks,
  failed payments, unused credits, and plan migrations affect the ledger.
- [ ] Add a visible usage history and clear explanation of credit expiration.
- [ ] Reconcile subscription payments against credit grants on a schedule.
- [ ] Add customer support contact, response targets, incident communication, and
  refund handling.

## Legal pages

- [ ] Publish Terms of Service.
- [ ] Publish Privacy Policy and cookie/analytics notice where required.
- [ ] Publish Acceptable Use, Voice/Content Rights, Refund, and Takedown policies.
- [ ] Offer a data processing agreement where the product acts as a processor.
- [ ] Verify marketing claims, plan limits, testimonials, and AI/security claims.

## Reliability and release

- [ ] Run PostgreSQL backup/restore and object-storage recovery exercises.
- [ ] Add structured logs, exception tracking, uptime monitoring, queue alerts,
  webhook failure alerts, and provider-spend alerts.
- [ ] Test worker termination, retry/idempotency, Redis outage, database outage,
  object-storage outage, provider rate limits, and duplicate webhooks.
- [ ] Establish staging with separate database, storage, keys, and billing test
  mode.
- [ ] Perform a load test using licensed synthetic fixtures, not customer media.
- [ ] Write rollback, incident, provider-outage, and key-rotation runbooks.
- [ ] Complete the production smoke test in `DEPLOYMENT.md`.

## Suggested release sequence

1. Local/staging acceptance with synthetic fixtures.
2. Invite-only alpha with no billing.
3. Private paid beta with manual onboarding and constrained usage.
4. Public waitlist while security, legal, email, deletion, and operations gates
   close.
5. Public registration only after the checklist is signed off.
