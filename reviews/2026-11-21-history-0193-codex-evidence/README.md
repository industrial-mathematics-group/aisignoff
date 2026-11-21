# Text with a Git binary diff

From the repository root, run:

```sh
uv sync --locked --group dev
uv run --no-project --with aisignoff==0.19.2 python reviews/2026-11-21-history-0193-codex-evidence/forced_binary.py "$PWD/.venv/bin/aisignoff" reviews/2026-11-21-pull57-codex-evidence/cache_cases.py
```

Each case uses a fresh temporary Git repository and turns off the cache. The branch replaces line 1 of a three-line text file. The main branch declares H1 and the pull request declares H3. The script prints the review level of each run of lines and the pair of added and removed counts. The control uses Git's ordinary text diff. The other case uses `-diff` in `.gitattributes`, which makes Git omit the text patch. [Recorded output](forced-binary-results.txt)
