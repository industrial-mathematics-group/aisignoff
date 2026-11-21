# Independent review of the aisignoff v0.19.1 codebase

- **Reviewer** — GPT Sol (OpenAI), new session without the generating conversation.
- **Reviewed** — industrial-mathematics-group/aisignoff on 2026-11-21. Whole-codebase snapshot at `d7bbede3c4e199988413320ad66230a0032ca066` (then `main`, tagged `v0.19.1`). The first parent and comparison release v0.19.0 is `10740ce003b4ac494b398a9d816bfac3a64d8acd`. [Reviewed revision](https://github.com/industrial-mathematics-group/aisignoff/tree/d7bbede3c4e199988413320ad66230a0032ca066)
- **Level** — A2 for whole files whose declarations identify tier-2 Claude Opus or human authorship, and A1 for whole files with any tier-1 Claude Fable contributions. GPT Sol is a different tier-2 model. All four reproduced findings are in the A1 scope.
- **Highest finding in the reviewed snapshot** — critical.

## Summary

The existing suite passed with one optional integration skip, and lint accepted the project’s declarations. The review found a garbage-collection case that silently removes a live record, a cache case that retains stale provenance, and two file-type edge cases. All four also reproduce on v0.19.0.

## What was checked

I read the package implementation, embedded HTML report and guides, packaging entry points, repository CI, and example workflows and migration scripts. I checked them against the documentation, examined relevant test coverage, and ran the full existing suite. Whole-file attestations cover the implementation, workflows, examples, packaging entry points, and the v0.19.1 regression test file. I used the per-line `Assisted-by` declarations to assign each attested file its level.

I checked the latest merge against the earlier review. The 13 release regression tests pass. They cover retained findings after unrelated reverts, finding order and lint for quoted table headers, and preservation of records for ordinary excluded files across renames and root commits. The separate cleanup parser still mishandles quoted headers, as finding 1 shows.

## Findings in the reviewed snapshot

### 1. Critical — Garbage collection can remove a live review record

[`src/aisignoff/cli.py:913`](../src/aisignoff/cli.py#L913), [`src/aisignoff/cli.py:971`](../src/aisignoff/cli.py#L971)

In the fixture, `SIGNOFF.toml` has a quoted `[[ "attestations" ]]` table for `dead` followed by a bare `[[attestations]]` table for `live`. Both attest H3 with the same reviewer. After `dead` is deleted, `gc --dry-run` correctly selects entry 1. The deletion routine skips quoted headers when counting entries and selects the bare table for `live`. The safety check compares declaration values alone, so the two records compare equal despite different target paths and blobs. The projected cleanup leaves `dead` in the file and drops the live file’s reported review from H3 to H1. Git history can recover the record, but the command's validation accepts the wrong deletion.

Recognise every table header layout that the deletion command supports and refuse layouts it cannot map to entries. Before writing, compare the complete parsed identities of retained records, including path, blob and commit, along with declaration values.

### 2. Major — The blame cache can retain stale provenance for binary files with non-ASCII names

[`src/aisignoff/history.py:1488`](../src/aisignoff/history.py#L1488), [`src/aisignoff/history.py:1496`](../src/aisignoff/history.py#L1496)

Commit `données.bin` at H1 and run `report --json` to warm the cache. Edit the bytes and commit the change at H3. The next cached report still says H1 for the file. The uncached report says H3. Git quotes the path in the newline-delimited change list, while the cache looks up the raw path. The missed invalidation carries the old commit into the new cache. `AISIGNOFF_NO_CACHE=1` gives the correct result.

Read the touched paths with Git’s NUL-delimited output and compare the raw path names to the cache keys. Add an incremental-cache case with a quoted path.

### 3. Major — A tracked dangling symlink cannot retain a whole-file review

[`src/aisignoff/history.py:961`](../src/aisignoff/history.py#L961), [`src/aisignoff/cli.py:874`](../src/aisignoff/cli.py#L874)

A committed symlink to an absent target appears in the project and is counted as one unit. `attest link --at HEAD` succeeds, but lint immediately says that the new record covers no line. Without `--at`, `attest link` exits 2 with `cannot hash link`. Resolution uses `is_file()`, which follows the symlink instead of recognising its Git entry, and the working-tree hash command opens the target. This affects a supported file type and defeats the whole-file review path.

Use a link-aware existence check throughout attestation resolution and hash symlink target text as the Git blob. Include a dangling symlink in the working-tree and historical attestation tests.

### 4. Minor — Staging an empty file changes the number of added units reported by `diff`

[`src/aisignoff/diff.py:102`](../src/aisignoff/diff.py#L102), [`src/aisignoff/diff.py:250`](../src/aisignoff/diff.py#L250)

After creating an empty file, `diff HEAD --json` reports one added unit. After staging the unchanged file, it reports zero. Deleting the empty file after committing it also reports zero removed units. Git emits a file header without a hunk, so the hunk parser returns no line numbers and the tracked entry skips the untracked-file fallback. The project’s unit-count rule treats an empty file as one unit.

Recognise empty-file additions and deletions when tallying changes and cover both the staged and untracked cases.

## Outside the latest merge

This review covers the full checked-out implementation, so existing defects in that snapshot count toward its finding level. For attribution to the latest merge alone, all four findings above are outside PR #55. Running the same checks on the previous release, at the first parent listed above, produced identical results.

## Evidence

[check.py](2026-11-21-full-codebase-codex-evidence/check.py) builds four disposable repositories. [v0.19.1 output](2026-11-21-full-codebase-codex-evidence/v0.19.1.txt) and [v0.19.0 output](2026-11-21-full-codebase-codex-evidence/v0.19.0.txt) are identical. The [run instructions](2026-11-21-full-codebase-codex-evidence/README.md) describe the cache control and the non-destructive check of the cleanup transform.

## Commands and results

| Command | Result |
|---|---|
| `git fetch --prune --tags origin` and `git rev-parse origin/main HEAD^1` | Full clone, reviewed head and first parent as listed above. |
| `uv sync --locked --group dev` | Loaded the locked environment on Python 3.13.5. Git version 2.47.3. |
| `uv run --locked aisignoff guide --role review` | History enabled, no minimum policy, records under `reviews/`. |
| `uv run --locked pytest -q -rs` | 362 passed, 1 skipped. The optional `anthropic` module was absent. |
| `uv run --locked --no-sync pytest -q -rs tests/test_review_019.py` | All 13 release regression tests passed. |
| `uv run --locked aisignoff lint` | Passed. 84 files and 16,090 lines had valid declarations. |
| `AISIGNOFF_NO_CACHE=1 uv run --locked aisignoff lint` | Same result. |
| `uv run --locked aisignoff report --json` and the same command with `AISIGNOFF_NO_CACHE=1` | Byte-identical JSON for this checkout, 84 files. |
| `uv run --locked aisignoff gc --dry-run` | Every checked-in record covers a line. |
| `uv run --locked aisignoff diff HEAD^ --files` | Produced the release diff by file. |
| `uv run --locked aisignoff report --html /tmp/aisignoff-full-report.html --with-source --since HEAD^` | Wrote the HTML report. |
| `uv run --locked aisignoff badge --out /tmp/aisignoff-full-badges` | Wrote all four badge files. |
| `git diff --check HEAD^ HEAD` | Passed. The release introduces no dependency or compatibility-bound changes. |
| `.venv/bin/python reviews/2026-11-21-full-codebase-codex-evidence/check.py` | Reproduced the four findings at v0.19.1. |
| `uv run --no-project --with aisignoff==0.19.0 python reviews/2026-11-21-full-codebase-codex-evidence/check.py` | Reproduced all four on v0.19.0. |

Verification used local Git and Python. Live GitHub and Anthropic workflow calls, browser interaction, and other Python versions are outside the verification performed.

BLOCKING
