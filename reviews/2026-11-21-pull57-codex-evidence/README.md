# Cache cases retained from the whole-file review

In a checkout of v0.19.2 containing this script, run:

```sh
uv sync --locked --group dev
uv run --no-project --with aisignoff==0.19.1 python reviews/2026-11-21-pull57-codex-evidence/cache_cases.py "$PWD/.venv/bin/aisignoff"
```

The script uses a disposable repository for each case. It primes the cache at H1, edits the binary in an H3 commit, and compares the cached and uncached review levels. The upgrade case runs v0.19.1 once after the edit so that v0.19.2 sees a stale entry already stored for the current commit. The output is in [cache-results.txt](cache-results.txt).
