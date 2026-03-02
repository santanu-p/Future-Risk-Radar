# Releasing

This project follows **Semantic Versioning** (`MAJOR.MINOR.PATCH`).

## Release checklist

1. Ensure CI is green on `main`.
2. Update `CHANGELOG.md` from `Unreleased` entries.
3. Align version fields across:
   - `backend/pyproject.toml`
   - `backend/src/frr/__init__.py`
   - `frontend/package.json`
   - `infra/helm/frr/Chart.yaml`
4. Create a release PR (if used in your workflow).
5. Tag release (`vX.Y.Z`) and publish GitHub Release notes.

## Versioning policy

- **MAJOR**: breaking API or behavior changes.
- **MINOR**: backward-compatible features.
- **PATCH**: backward-compatible bug fixes.
