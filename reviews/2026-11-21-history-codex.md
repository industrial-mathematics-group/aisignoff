# Independent whole-file review of aisignoff history resolution

- **Reviewer** — GPT Sol (OpenAI), new session without the generating conversation.
- **Reviewed** — `src/aisignoff/history.py` in full at `cc9cd721e74e4e6d11a056dbfb1f6cd3536a2aa3` on 2026-11-21. The blob is `8c2731fa986e3c3d13c40f5e434f436e3d962e49`. The immediate base `6ec289181e2f1f10d8684aa938f2a9a1738f5ed7` contains the same blob. The previous release comparison used v0.19.1 at `d7bbede3c4e199988413320ad66230a0032ca066`.
- **Level** — A1. Current per-line generation declarations include Claude Fable (tier 1) and Claude Opus (tier 2). GPT Sol is tier 2.
- **Highest finding in the reviewed file** — major.

## Summary

The file still has a major cache finding and has a second major provenance defect when a branch replaces a binary file with text. The current snapshot showed 1,727 lines at F2 and 44 at F0 before this review. A new whole-file attestation records the highest severity for the file's reviewed content, so its F2 marker applies to all covered lines. The findings below identify the affected logic.

## What was checked

I read all of `history.py`, including parsing declarations, choosing the default branch and first-parent owners, resolving generation and review precedence, applying attestations across edits and renames, classifying dead records, and mapping blame to changed lines. I read the adjacent diff parser, cache and project resolution code, and checked the behavior against the history documentation, prior review records, and tests. The existing suite passed and I verified the two cache cases from the prior review and the binary-to-text case on both releases.

## Findings in the reviewed file

### 1. Major — Replacing a binary with text can attribute new lines to the old binary's commit

[`src/aisignoff/history.py:1565`](../src/aisignoff/history.py#L1565), [`src/aisignoff/history.py:1419`](../src/aisignoff/history.py#L1419), [`src/aisignoff/diff.py:169`](../src/aisignoff/diff.py#L169)

Commit a binary containing a NUL and three newline-delimited chunks at H1. Replace it with three entirely new text lines on a branch whose pull request declaration is H3. In both releases, `report --json --base main --declare-from` reports line 1 as H3 and lines 2–3 as H1. The diff parser represents a binary patch as one added unit and one removed unit. History sees text in the working tree and uses that one-unit patch as a textual line map, then treats the rest of the new file as surviving blame rows from the binary base. The PR preview can therefore display stale levels even though the landed text is entirely new.

Carry the old and new file classifications into the line mapper. When a binary becomes text, all new text lines should take pending provenance. Keep the one-unit rule for the old binary. Add a regression test with a multiline binary base and text with no surviving lines.

### 2. Major — An upgrade can continue to use stale unit provenance

[`src/aisignoff/history.py:1510`](../src/aisignoff/history.py#L1510), [`src/aisignoff/cache.py:170`](../src/aisignoff/cache.py#L170)

The previous review found that a stale unit entry saved by v0.19.1 for the current commit persists when v0.19.2 reads it. I reran the example against this snapshot. Cached output still reports H1 for the edited binary while uncached output reports H3. Invalidate cached unit origins created before the fix and document the upgrade path.

### 3. Minor — Leading newlines in filenames still cause stale incremental results

[`src/aisignoff/history.py:1530`](../src/aisignoff/history.py#L1530)

The prior fixture for a binary named `\nreport.bin` still reports cached H1 and uncached H3. The current code strips a real leading newline from the NUL-delimited path. Preserve the first byte of each filename when processing Git's output.

## Outside this review

The target is a whole file. All three findings reproduce on the previous release. The immediate base adds no changes to this file. The scope here is history resolution and its direct dependencies.

## Evidence

- [changed_units.py](2026-11-21-history-codex-evidence/changed_units.py) and [recorded output](2026-11-21-history-codex-evidence/changed-units-results.txt) reproduce the incorrect ownership mapping.
- The previously committed [cache cases](2026-11-21-pull57-codex-evidence/cache_cases.py) produced their [recorded results](2026-11-21-pull57-codex-evidence/cache-results.txt) again.

## Commands and results

| Command | Result |
|---|---|
| `git rev-parse HEAD HEAD^1 HEAD:src/aisignoff/history.py HEAD^1:src/aisignoff/history.py` | Confirmed the snapshot, parent and identical file blobs. |
| `uv sync --locked --group dev` and `uv run --locked aisignoff guide --role review` | Environment synced, history enabled, review folder `reviews/`. |
| `uv run --locked pytest -q -rs` | 374 passed and one optional Anthropic SDK test skipped. |
| `uv run --locked aisignoff lint` | Passed for 85 files and 16,306 lines. |
| `AISIGNOFF_NO_CACHE=1 uv run --locked aisignoff report --json` | Confirmed the existing F2/F0 split and generating models. |
| `uv run --locked aisignoff gc --dry-run` | Every record covers a line. |
| `uv run --no-project --with aisignoff==0.19.1 python reviews/2026-11-21-history-codex-evidence/changed_units.py "$PWD/.venv/bin/aisignoff"` | Both releases assign H3 to line 1 and H1 to lines 2–3. |
| `uv run --no-project --with aisignoff==0.19.1 python reviews/2026-11-21-pull57-codex-evidence/cache_cases.py "$PWD/.venv/bin/aisignoff"` | Both cache defects reproduced. |

Local verification used Linux, Python 3.13 and Git 2.47.3. Live provider calls were outside the scope.

BLOCKING
