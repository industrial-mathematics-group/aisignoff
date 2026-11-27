# Commit badge checks

From the checkout, after syncing the locked development environment:

```sh
uv run --locked python reviews/2026-11-27-v0.24.0-codex-evidence/badge_cases.py "$PWD/.venv/bin/aisignoff" reviews/2026-11-21-pull57-codex-evidence/cache_cases.py
```

The script compares commit badges with file badges and lint in two disposable repositories with the cache disabled. One uses a version-3 self-check, and one uses conflicting H0 and H3 trailers. [Recorded output](results.txt)
