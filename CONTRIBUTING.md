# Contributing

Thanks for helping improve AI Voice Translator. The project is in private beta,
so small, well-scoped changes are easier to review and safer to ship.

## Before you start

1. Search existing issues and pull requests.
2. Open an issue for substantial product, schema, provider, or architecture
   changes before writing code.
3. Never use customer media, credentials, transcripts, or generated artifacts as
   fixtures.
4. Keep synthetic voice work behind explicit rights and consent controls.

## Development setup

Follow the README quick start, then create a focused branch:

```bash
git switch -c fix/short-description
```

The development topology uses SQLite, local storage, and in-process jobs. Run
database migrations whenever models change:

```bash
flask --app app db migrate -m "describe the schema change"
flask --app app db upgrade
```

Inspect generated migrations before committing them.

## Quality checks

Run all checks relevant to your change:

```bash
pytest -q
npm run build --prefix frontend
npm audit --prefix frontend
pip check
```

Add or update tests for behavior changes. Avoid tests that call paid providers or
depend on the network.

## Pull requests

- Keep one concern per pull request.
- Explain user impact, implementation, testing, and operational considerations.
- Include screenshots for UI changes.
- Call out schema migrations, environment variables, billing behavior, security
  implications, and compatibility changes.
- Do not commit `.env`, provider keys, source audio, transcripts, output files,
  database files, or secrets of any kind.

By contributing, you confirm you have the right to submit the contribution.
