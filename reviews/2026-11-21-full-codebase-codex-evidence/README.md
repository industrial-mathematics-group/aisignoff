# Checks for the full-codebase review

Run from a checkout of aisignoff v0.19.1 with Git, Python and uv available.

```sh
uv sync --locked --group dev
uv run --locked python reviews/2026-11-21-full-codebase-codex-evidence/check.py
uv run --no-project --with aisignoff==0.19.0 python reviews/2026-11-21-full-codebase-codex-evidence/check.py
```

The script builds disposable Git repositories and prints the four observed failures. It disables the blame cache except in the explicitly cached runs. The garbage-collection case uses the CLI dry run and projects its cleanup in memory before checking the resulting provenance in a fixture. The two text files contain stdout from each version.
