# Unit counting and cleanup checks

Run from the review checkout after `uv sync --locked --group dev`.

```sh
uv run --no-project --with aisignoff==0.22.0 python reviews/2026-11-25-v0.23.0-codex-evidence/unit_boundaries.py "$PWD/.venv/bin/aisignoff" reviews/2026-11-21-pull57-codex-evidence/cache_cases.py
```

[Recorded output](results.txt) compares the two releases in fresh Git repositories with the blame cache disabled. It covers a changed symlink target with newlines, a binary-to-text transition with only an insertion, and a pull request that removes a legacy unknown key.
