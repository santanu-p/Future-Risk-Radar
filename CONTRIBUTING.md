# Contributing to Future Risk Radar

Thanks for your interest in contributing to Future Risk Radar (FRR)! We welcome bug fixes, docs improvements, tests, and feature work.

## Ground rules

- Be respectful and follow our [Code of Conduct](./CODE_OF_CONDUCT.md).
- For security issues, **do not file a public issue**. Follow [SECURITY.md](./SECURITY.md).
- Keep pull requests focused and small when possible.

## Quick start

### 1) Fork and clone

1. Fork this repository.
2. Clone your fork and create a branch from `main`.

### 2) Local setup

1. Copy env template:
   - `.env.example` → `.env`
2. Start core dependencies:
   - `make up`
3. Backend setup and run:
   - `cd backend`
   - `uv sync`
   - `uv run uvicorn frr.main:app --reload`
4. Frontend setup and run (new terminal):
   - `cd frontend`
   - `npm install`
   - `npm run dev`

## Development workflow

### Quality checks

Before opening a PR, run:

- `make lint`
- `make typecheck`
- `make test`
- `make test-frontend`

### Commit style and DCO sign-off

Use clear commit messages.

Please sign off commits using DCO:

- `git commit -s -m "your message"`

By signing off, you certify you have the right to submit the work under this project license.

## Pull request process

1. Open a PR against `main`.
2. Fill out the PR template completely.
3. Ensure CI passes.
4. Address review feedback.

## Reporting issues and requesting features

- Use the issue templates in GitHub.
- Include reproduction details for bugs.
- For feature requests, explain the user value and possible implementation approach.

## Documentation contributions

Docs improvements are welcome and can be submitted independently from code changes.

## Questions

Use [SUPPORT.md](./SUPPORT.md) for support channels.
