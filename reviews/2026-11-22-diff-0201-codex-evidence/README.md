# Working-tree encoding and landed provenance checks

Run from the aisignoff v0.20.1 checkout.

```sh
uv sync --locked --group dev
uv run --no-project --with aisignoff==0.20.0 python reviews/2026-11-22-diff-0201-codex-evidence/encoding.py "$PWD/.venv/bin/aisignoff" reviews/2026-11-21-pull57-codex-evidence/cache_cases.py
```

The script creates disposable Git repositories with the cache disabled. First it replaces one line in a three-line file, once with ordinary UTF-8 and once with Git's `working-tree-encoding=UTF-16LE`. It prints the diff totals and the review levels attached to the removed units. Then it checks provenance after committing a binary-to-text replacement on the default branch. [Recorded stdout](encoding-results.txt)
