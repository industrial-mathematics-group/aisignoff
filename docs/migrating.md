# Upgrading

Check the [changelog](changelog.md) for **Breaking** changes before raising the version your workflows pin. A [snapshot](snapshots.md) keeps the levels of existing lines through any upgrade.

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

aisignoff reads only `SIGNOFF.toml` with `version = 3` and the inline tags of that version. `AIDECL.toml` (the name up to aidecl 0.3.0), format version 1 (one verification axis, `AI-Verification: V0`–`V3`, `Tested-by`, `Verified-by`) and format version 2 (the AI review scale `A-`, `A0`–`A3`, which moved up by one) are no longer read since 1.0.0rc2: `lint` stops with an error for `AIDECL.toml` and old versions of `SIGNOFF.toml`, and old inline tags aren't recognised as a declaration.

Convert such a repository once with 1.0.0rc1, the last release with `aisignoff migrate`, then raise the version you pin:

```bash
uvx aisignoff==1.0.0rc1 migrate --dry-run   # or: pipx run aisignoff==1.0.0rc1 migrate --dry-run
uvx aisignoff==1.0.0rc1 migrate
git add -A SIGNOFF.toml AIDECL.toml         # both sides of the rename, if there was one
```

It renames `AIDECL.toml` to `SIGNOFF.toml` and converts versions 1 and 2, keeping comments and layout for version 2. A repository with only inline tags on the version-2 scale needs `migrate --from 2`. What the old levels don't say, such as the human review of a V1 file, is marked `TODO`, which `lint` reports until a person fills it in. The [documentation of 1.0.0rc1](https://github.com/industrial-mathematics-group/aisignoff/blob/v1.0.0rc1/docs/migrating.md) has the full conversion tables.

Projects renamed from aidecl also switch the badge URLs to `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json`.
