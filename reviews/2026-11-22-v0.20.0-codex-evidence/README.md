# Reproduction cases for the v0.20.0 review

From an aisignoff v0.20.0 checkout, run:

```sh
uv sync --locked --group dev
uv run --no-project --with aisignoff==0.19.3 python reviews/2026-11-22-v0.20.0-codex-evidence/diff_edges.py "$PWD/.venv/bin/aisignoff" reviews/2026-11-21-pull57-codex-evidence/cache_cases.py
node reviews/2026-11-22-v0.20.0-codex-evidence/syntax_cases.cjs
```

The diff script uses fresh Git repositories with the blame cache disabled. It prints the reported review runs, Git's raw numstat and the aisignoff addition and removal totals for each case. [Recorded diff output](diff-edges-results.txt)

The syntax script runs the shipped bundle and the report's actual highlighting functions without a DOM. The review ran the same function in V8. The control detects Python with a plain shebang and preserves a multiline string. The flagged Python shebang is incorrectly detected as Bash. [Recorded syntax output](syntax-results.json)
