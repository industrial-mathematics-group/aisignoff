# Upgrading

Check the [changelog](changelog.md) for **Breaking** changes before raising the version your workflows pin. A [snapshot](snapshots.md) keeps the levels of existing lines through any upgrade. `aisignoff migrate` converts the older formats below, all or nothing; run it with `--dry-run` first.

## From 0.11 or earlier, with `[history]`

0.12 introduced [one owner per line](history.md#one-owner-per-line): a review declared by a commit inside a pull request, or by a pull request merged into another one, no longer counts. Some lines of existing code can report other levels after the upgrade. To keep what 0.11 reported, write a snapshot with 0.11 before upgrading, using [`freeze-from-0.11.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/freeze-from-0.11.py):

```bash
git switch --detach origin/main
uv run --no-project --with aisignoff==0.11.0 python freeze-from-0.11.py
git switch -c freeze && git add SIGNOFF.snapshot.json && git commit -m "Freeze the declarations of 0.11"
```

Without it, run `aisignoff lint` after upgrading and settle what it reports: move `[[commits]]` review entries for commits inside pull requests to the merge commit (or attest the file), and declare merged templates without a ticked generation or human review box with a `[[commits]]` entry.

## From aidecl

aidecl (up to 0.3.0) was renamed to aisignoff. Keys, levels and inline tags are the same.

1. Reinstall: `pipx uninstall aidecl && pipx install aisignoff`.
2. Run `aisignoff migrate`: it renames `AIDECL.toml` to `SIGNOFF.toml` (converting format 1 or 2 in the same step). Commit both sides of the rename: `git add -A SIGNOFF.toml AIDECL.toml`.
3. Update the badge URLs: the files are now `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json`.

Until then, aisignoff reads `AIDECL.toml` with a warning. Having both files is an error.

## From format version 2

Version 2 had the AI review scale A-, A0–A3, which moved up by one. Only `AI-Review` (and `ai` in `[policy]`) changes; comments and layout of `SIGNOFF.toml` are kept.

| Old | New |
|---|---|
| A- (none) | A0 |
| A0 (self-check) | A1; for G0 `TODO`, since human-written content has no self-check |
| A1 (independent session) | A2 |
| A2 (different model) | A2, with a note to raise it to A3 if the review was extensive or benchmarked |
| A3 (different model with benchmark) | A3 |

A repository with inline tags and no `SIGNOFF.toml` doesn't say which scale its tags use: run `aisignoff migrate --from 2`. It converts the tags and creates a version-3 `SIGNOFF.toml`, which records the conversion so the tags are never shifted twice.

## From format version 1

Version 1 had one verification axis, V0–V3:

| Old | New |
|---|---|
| V0 (human, line by line) | H2, and A0 for G0 |
| V1 / V2 (independent agent, same / different model) | A2 |
| V3 (human + independent agent) | H2 + A2 |
| `Tested-by` | `Reviewed-by` |
| `Verified-by` | `AI-Reviewed-by` |

Comments in `SIGNOFF.toml` aren't carried over from version 1.

## TODOs after migrating

What the old levels don't say, such as the human review of a V1 file, has to be added by a person. `migrate` marks it with a `TODO` comment in `SIGNOFF.toml` or a `TODO` value in inline tags, and `lint` reports it until it's filled in.
