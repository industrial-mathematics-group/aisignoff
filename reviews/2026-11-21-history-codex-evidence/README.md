# Binary-to-text provenance check

Run from the checkout after syncing the locked development environment.

```sh
uv run --no-project --with aisignoff==0.19.1 python reviews/2026-11-21-history-codex-evidence/changed_units.py "$PWD/.venv/bin/aisignoff"
```

The script compares v0.19.1 and the checked-out v0.19.2 in fresh temporary repositories with the cache disabled. Each repository has an H1 binary committed on main, followed by replacement with three new lines on a branch whose pull request declares H3. The expected provenance is H3 for all three lines. The [recorded output](changed-units-results.txt) shows H1 for lines 2 and 3 in both releases.
