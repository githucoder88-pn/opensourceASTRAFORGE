# Pending CI workflow

`ci.yml` here is the project's complete GitHub Actions pipeline. It lives in
`workflows-pending/` rather than `workflows/` only because the automation that
created this branch lacks the GitHub `workflows` permission and cannot push
files into `.github/workflows/`.

**To activate CI, move it into place and commit:**

```bash
mkdir -p .github/workflows
git mv .github/workflows-pending/ci.yml .github/workflows/ci.yml
git rm .github/workflows-pending/README.md
git commit -m "ci: enable GitHub Actions pipeline"
git push
```

## What the pipeline does

| Job | Purpose |
| --- | --- |
| `test` | ruff, `mypy --strict` and the full suite on Python 3.10/3.11/3.12 (Linux) and 3.12 (macOS) |
| `demo` | installs the package **without dev extras** and runs every example, so the demos can never silently start depending on a dev-only package |
| `build` | builds the wheel and validates the metadata with `twine check` |

The `demo` job exists because of a real bug: the flagship example once invoked
pytest, which passed in the development environment and failed on a clean
`pip install`. All checks pass locally as of the latest commit.
