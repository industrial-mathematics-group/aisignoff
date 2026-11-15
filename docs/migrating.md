# Upgrading

Check the [changelog](changelog.md) for **Breaking** changes before raising the version your workflows pin. A [snapshot](snapshots.md) keeps the levels of existing lines through any upgrade.

## To `SIGNOFF.toml` version 4: the AI review scale of 1.0.0rc6

1.0.0rc6 changes what the AI review levels mean, so that the scale counts only review that is independent of the session that wrote the content ([Levels and rules](levels.md#ai-review-a0-to-a3)):

| Version 3 | Version 4 | Note |
|---|---|---|
| A0 none | A0 no independent AI review | |
| A1 self-check by the generating session | A0 | `AI-Reviewed-by` is dropped |
| A2 review by a new session | A1 context-free check | A2 if the reviewer is a different, capable model |
| A3 extensive review or benchmark by a different model | A3 validated by a different model | lower it to A2 if the reviewer only read and produced nothing new |

Two built-in rules are gone: G1–G3 no longer need an AI review, and G0 content can have any level. In `[policy]`, `ai = "A1"` becomes `"A0"` and `ai = "A2"` becomes `"A1"`; for G0, where A1 meant a new session, both become `"A1"`.

Raising the version you pin changes nothing by itself. aisignoff reads `SIGNOFF.toml` with `version = 3` as before and takes its levels over with this table: those of the file, of inline tags, of commit messages and pull request descriptions (so the old pull request template keeps working), and of a snapshot. Reports show today's levels, and `lint` adds a note. `annotate` and `attest` refuse until the file is version 4.

Change over in one pull request per repository, once your workflows pin 1.0.0rc6 or later:

1. **With `[history]`, write a snapshot:** `aisignoff freeze` on the default branch, landed as usual ([Snapshots](snapshots.md)). Commit messages can't be rewritten, and from version 4 on they are read on the new scale: the snapshot keeps what the commits so far declare, as taken over.
2. **Convert the file** with [`convert-to-version-4.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/convert-to-version-4.py): `python convert-to-version-4.py` at the repository root (`--dry-run` shows the change only). It rewrites the levels and `[policy]` with the table, sets `version = 4`, keeps comments and layout, and writes nothing if the result wouldn't be read as the same declarations.
3. **Change the AI review boxes of the pull request template** in the same pull request, to the wording in [Pull request descriptions](history.md#pull-request-descriptions). With version 4, a ticked A1 box that still says "checked its own work" is an error. Do the same for the issue form of the signoff request, if you use it.
4. **Edit inline tags by hand.** The script lists the files that may have one with A1 or A2.
5. **Look at each A3:** it now says that the reviewer produced new evidence and left a record.

The pull request that changes over is itself read on the new scale already, since its own `SIGNOFF.toml` says version 4: replace the AI review boxes in its description with the new ones by hand, because GitHub fills in the template of the default branch. If it changes an `ai` minimum in `[policy]`, a maintainer lands it ([Checking the pull request description](ci.md#checking-the-pull-request-description)).

After the change, commit messages from before it that the snapshot doesn't hold are read on the new scale: lines of a file that `freeze --reset` works out again, and commits that land from branches opened before. Correct those with a `[[commits]]` entry.

## From 0.11 or earlier, with `[history]`

0.12 introduced [one owner per line](history.md#one-owner-per-line): a review declared by a commit inside a pull request, or by a pull request merged into another one, no longer counts. Some lines of existing code can report other levels after the upgrade. To keep what 0.11 reported, write a snapshot with 0.11 before upgrading, using [`freeze-from-0.11.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/freeze-from-0.11.py):

```bash
git switch --detach origin/main
uv run --no-project --with aisignoff==0.11.0 python freeze-from-0.11.py
git switch -c freeze && git add SIGNOFF.snapshot.json && git commit -m "Freeze the declarations of 0.11"
```

Land this snapshot while your CI still runs 0.11, and raise the version your workflows pin in a later pull request. A newer aisignoff checks a changed snapshot by working it out again under its own rules, and a snapshot written under 0.11's rules can't be compared, so it fails as a change. Once it is on the default branch, it is accepted as it is.

Without it, run `aisignoff lint` after upgrading and settle what it reports: move `[[commits]]` review entries for commits inside pull requests to the merge commit (or attest the file), and declare merged templates without a ticked generation or human review box with a `[[commits]]` entry.

## From aidecl, or format version 1 or 2

aisignoff reads only `SIGNOFF.toml` with `version = 4` or `3` and the inline tags of those versions. `AIDECL.toml` (the name up to aidecl 0.3.0), format version 1 (one verification axis, `AI-Verification: V0`–`V3`, `Tested-by`, `Verified-by`) and format version 2 (the AI review scale `A-`, `A0`–`A3`, which moved up by one) are no longer read since 1.0.0rc2: `lint` stops with an error for `AIDECL.toml` and old versions of `SIGNOFF.toml`, and old inline tags aren't recognised as a declaration.

Convert such a repository once with 1.0.0rc1, the last release with `aisignoff migrate`, then raise the version you pin:

```bash
uvx aisignoff==1.0.0rc1 migrate --dry-run   # or: pipx run aisignoff==1.0.0rc1 migrate --dry-run
uvx aisignoff==1.0.0rc1 migrate
git add -A SIGNOFF.toml AIDECL.toml         # both sides of the rename, if there was one
```

It renames `AIDECL.toml` to `SIGNOFF.toml` and converts versions 1 and 2, keeping comments and layout for version 2. A repository with only inline tags on the version-2 scale needs `migrate --from 2`. What the old levels don't say, such as the human review of a V1 file, is marked `TODO`, which `lint` reports until a person fills it in. The [documentation of 1.0.0rc1](https://github.com/industrial-mathematics-group/aisignoff/blob/v1.0.0rc1/docs/migrating.md) has the full conversion tables.

Projects renamed from aidecl also switch the badge URLs to `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json`.
