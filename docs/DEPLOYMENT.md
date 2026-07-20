# Production deployment

This runbook uses Railway for the web/API and worker processes, managed
PostgreSQL and Redis, Cloudflare R2 or another S3-compatible store for files,
and Lemon Squeezy as Merchant of Record.

## 1. Create external resources

Create these resources before enabling production mode:

1. A PostgreSQL database.
2. A Redis database.
3. A private S3/R2 bucket with an API token restricted to that bucket.
4. An OpenAI API project with spending limits and alerts.
5. A Lemon Squeezy store with two monthly variants: Creator ($29) and Studio
   ($79).
6. A custom domain with HTTPS.

Do not reuse personal root credentials for production object storage.

## 2. Deploy the web service

Connect the repository to Railway and deploy the repository root containing
`app.py`. The included `nixpacks.toml` installs Python, Node.js 22, and FFmpeg,
then builds the React application.

Use this start command for the web service:

```bash
gunicorn app:app --timeout 120 --workers 1 --worker-class gthread --threads 4 --bind 0.0.0.0:$PORT
```

Configure the health check path as `/health`.

Run this as Railway's pre-deploy command:

```bash
flask --app app db upgrade
```

Do not run multiple migration processes at the same time.

## 3. Deploy the worker service

Create a second Railway service from the same repository and variables. Override
its start command with:

```bash
rq worker --url "$REDIS_URL" pipeline
```

The `Procfile` documents the web, worker, and release process commands, but a
single Nixpacks service selects only one process. Set the worker command on the
worker service explicitly.

Long jobs have a six-hour RQ timeout. Start with one worker while measuring API
rate limits and memory use, then scale deliberately.

## 4. Production variables

Start from `.env.example`. These values are mandatory for production:

```dotenv
APP_ENV=production
APP_SECRET_KEY=<at-least-32-random-bytes>
APP_BASE_URL=https://app.yourdomain.com
ALLOW_BASIC_AUTH=false
DATABASE_URL=<railway-postgres-url>

OPENAI_API_KEY=<server-side-project-key>
OPENAI_TRANSLATION_MODEL=gpt-5.6-terra
OPENAI_TRANSCRIPTION_MODEL=whisper-1
OPENAI_TRANSLATION_REASONING_EFFORT=low

REDIS_URL=<railway-redis-url>
JOB_EXECUTION_MODE=rq
RATELIMIT_STORAGE_URI=<same-redis-url>

STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_BUCKET=<private-bucket-name>
S3_ACCESS_KEY_ID=<bucket-scoped-key>
S3_SECRET_ACCESS_KEY=<bucket-scoped-secret>

LEMONSQUEEZY_API_KEY=<api-key>
LEMONSQUEEZY_STORE_ID=<numeric-store-id>
LEMONSQUEEZY_WEBHOOK_SECRET=<random-webhook-secret>
LEMONSQUEEZY_CREATOR_VARIANT_ID=<numeric-variant-id>
LEMONSQUEEZY_STUDIO_VARIANT_ID=<numeric-variant-id>
```

Generate a secret locally, for example:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

`APP_ENV=production` activates secure cookies and boot-time safety checks. The
service will fail fast if PostgreSQL, Redis/RQ, S3, HTTPS, the application
secret, or the OpenAI key is missing.

## 5. Configure Lemon Squeezy

Create a webhook pointing to:

```text
https://app.yourdomain.com/api/billing/webhooks/lemonsqueezy
```

Subscribe to these events:

- `subscription_created`
- `subscription_updated`
- `subscription_cancelled`
- `subscription_resumed`
- `subscription_expired`
- `subscription_paused`
- `subscription_unpaused`
- `subscription_payment_success`

Use the same signing secret in Lemon Squeezy and
`LEMONSQUEEZY_WEBHOOK_SECRET`. Checkout custom data links a subscription to the
organization. Webhook bodies are HMAC-SHA256 verified and successful payloads
are deduplicated before granting credits.

Test creation, renewal, plan status changes, portal access, duplicate delivery,
and invalid signatures in Lemon Squeezy test mode before enabling live mode.

## 6. DNS and smoke test

After the custom domain is active:

1. Verify `GET /health` returns `{"status":"ok"}`.
2. Register a fresh account and confirm 15 credits.
3. Create a project, confirm rights/consent, and upload a short licensed file.
4. Run a one-language preview and download its three JSON artifacts.
5. Complete a test subscription checkout and verify credits appear once.
6. Restart web and worker services; confirm the account, project, job, and
   artifact still exist.
7. Confirm logs contain no API keys, checkout tokens, source audio, or transcript
   contents.

## 7. Backups and operations

- Enable PostgreSQL backups and perform a restore rehearsal.
- Configure object lifecycle rules only after the application has an explicit
  retention/deletion workflow.
- Add error tracking, uptime checks, queue-depth alerts, provider-spend alerts,
  and a webhook failure alert.
- Rotate secrets after any exposure and before leaving private beta.
- Keep the web process stateless. Never depend on Railway's ephemeral filesystem
  for source or generated files.

Railway references:

- https://docs.railway.com/guides/flask
- https://docs.railway.com/guides/saas-backend
- https://docs.railway.com/config-as-code/reference

Lemon Squeezy references:

- https://docs.lemonsqueezy.com/api/checkouts/create-checkout
- https://docs.lemonsqueezy.com/help/webhooks/signing-requests
- https://docs.lemonsqueezy.com/help/webhooks/event-types
- https://docs.lemonsqueezy.com/guides/developer-guide/customer-portal
