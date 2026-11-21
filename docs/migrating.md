# Upgrading

Check the [changelog](changelog.md) for **Breaking** changes before raising the version your workflows pin. Every line is worked out from the whole history on each run, so a release that changes how a line is read can change the levels of existing lines; the changelog says when.

## To 0.18: who writes what

0.18 splits the records by who writes them: `SIGNOFF.toml` is the file a person signs off, and the review folder holds the AI reviews. Nothing that is there today changes its meaning.

1. **Raise the pin to 0.18** in your workflows, and update the signoff request and `@signoff` assistant workflows if you copied them: they pass `attest --signoff` to keep writing into `SIGNOFF.toml`.
2. **Scripts and agents that run `attest -a`** without `-H` now get a new file in `reviews/`; commit it with the change, in a pull request of its own as a review. Add `--signoff` where a person records the review in `SIGNOFF.toml`.
3. **Give `SIGNOFF.toml` a code owner** and require their review ([Who writes what](signoff-toml.md#who-writes-what)), so that a change to it needs a person's approval.
4. **Optionally run `aisignoff gc --dry-run`** on the default branch to see which records cover no line any more, and `aisignoff gc` in a pull request to delete them.

## To 0.17: no snapshots

0.17 removes `aisignoff freeze` and `SIGNOFF.snapshot.json`. Every line is worked out from the whole history again, and a [cache](cache.md) in `.git/aisignoff` keeps that fast. A [[commits]] entry or an attestation now counts for every line it is about, however old. `lint` fails while a `SIGNOFF.snapshot.json` is there, because its levels and archived entries would otherwise be lost without notice.

1. **Move what the snapshot says into `SIGNOFF.toml`** with [`unfreeze.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/unfreeze.py), with 0.17 installed, at the repository root on a branch of the default branch: `python unfreeze.py` (`--dry-run` shows the change only). It puts the entries of the snapshot's archive back into `SIGNOFF.toml`, adds a `[[commits]]` entry for each commit whose lines the snapshot gave other levels than the history does, lists the lines that still differ, and deletes the snapshot. Look over the result, then commit both in one pull request that also raises the version your workflows pin to 0.17. An older aisignoff fails this pull request without the snapshot (it reports landed commits with the old template as errors), so a check that runs the workflow of the default branch, such as one on `pull_request_target`, fails until a maintainer lands it.
2. **Settle what `lint` reports.** Entries that came back from the archive are checked again: one for a commit inside a pull request counts only for `AI-Generation`, so delete it if it says nothing else. Commits that look like pull requests and declare nothing are a warning again; declare them with `[[commits]]` entries, or accept every commit up to one with `[history] require-trailers-since`.
3. **Keep the cache in CI** with the `actions/cache` step in [The blame cache](cache.md#in-ci), so that `lint` stays fast on a long history.

Commits of the default branch whose message has the ticked boxes of the pull request template before version 4 are now read as they were meant (the self-check is A0) instead of failing; a pull request description with that template still fails.

## A1 gives its findings

From 1.0.0rc10 on, a review of A1 gives its findings like A2 and A3, so that there is a reference for what a different model finds:

- **A pull request that declares A1 needs the line `AI-Review-Findings:`** with `none` or a severity (no report). If your pull request template has the line only next to the A2 and A3 boxes, or says it can be left empty for A1, change it. `attest -a A1` needs `--findings`.
- **Existing history is read as it is.** A landed A1 commit without the line leaves its lines at F-, as before; an A1 commit that gave the line now gives its lines those findings.
- **Update the examples** you copied: the signoff request form and workflow, and the `@signoff` assistant, now ask what an AI review found and need it to attest an AI review.

## To the findings axis

The reviewer only reviews, and its findings are recorded instead of blocking the merge:

- **A major or critical finding no longer fails `lint`.** It shows as F2 or F3 on the lines its review covered, until a later review of those lines finds them fixed. Fixing what a review found is the author's work, in the same pull request or a later one; have it reviewed again to bring the lines to F0.
- **Remove `[review]` `recheck`** from `SIGNOFF.toml` (`lint` warns while it is there), and `--recheck` from `aisignoff init` calls in workflows.
- **Existing history is read as it is.** Commits that gave `AI-Review-Findings:` with A2 or A3 give their lines those findings; older commits leave theirs at F-.
- **Report links** with `axis=gap` open the generation axis now.

## To 1.0.0rc8

Nothing to do for most repositories. What can change a result:

- A2 and A3 name a report that the pull request adds (or a link); since 0.16.0, modifying an earlier report fails. A description copied from an earlier pull request, whose report is already on the default branch, fails now.
- A pull request can't change the entries of `.git-blame-ignore-revs`: a maintainer commits them, or the workflow passes `--allow-policy-change`.
- A severe `AI-Review-Findings:` that has landed is cleared by the fix and its new review. `[[commits]]` entries written only to clear one can stay, or go.
- `AI-Review-Findings:` is no longer read next to A0 and A1, and a commit is judged by the `[review]` `recheck` of the `SIGNOFF.toml` it landed on.

## To 1.0.0rc7: no declarations in files

From 1.0.0rc7 on, a declaration comes only from `SIGNOFF.toml` and from git (commit messages, pull request descriptions, blame). The content of a file is never read for one, so **inline tags** (`# AI-Generation: G2` in a header comment) no longer declare anything, and `annotate --inline` is gone. A file that only its tags declared becomes undeclared, and one whose tags differed from its annotation falls back to the annotation.

Before you raise the pinned version, move the tags into `SIGNOFF.toml` with [`inline-tags-to-toml.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/inline-tags-to-toml.py), run with the last release that reads them:

```bash
uv run --with aisignoff==1.0.0rc6 python inline-tags-to-toml.py   # --dry-run shows the change only
```

It appends one annotation per tagged file, with exactly the declaration the file has today, and writes nothing if the result would differ. The tag comments can then be deleted whenever the files are next edited.

**Still on `SIGNOFF.toml` version 3? Move the tags first, then convert.** On version 3 the script writes the levels as the tags say them, on the scale of version 3, so that [`convert-to-version-4.py`](#to-signofftoml-version-4-the-ai-review-scale-of-100rc6) converts them with the rest of the file and checks the result. Converting first would make rc6 read the unconverted tags on the new scale, and the script would copy that: a self-check (A1 of version 3) would become today's A1, and a new session (A2) today's A2. Use the script of 1.0.0rc8 or later for this; the one of 1.0.0rc7 refused version 3.

The check of a review also reads no file any more: A2 and A3 give `AI-Review-Findings:` and name their report in `AI-Reviewed-by`, and what the report looks like is up to the repository ([The record of a review](levels.md#the-record-of-a-review)).

## To `SIGNOFF.toml` version 4: the AI review scale of 1.0.0rc6

1.0.0rc6 changes what the AI review levels mean, so that the scale counts only review that is independent of the session that wrote the content ([Levels and rules](levels.md#ai-review-a0-to-a3)):

| Version 3 | Version 4 | Note |
|---|---|---|
| A0 none | A0 no independent AI review | |
| A1 self-check by the generating session | A0 | `AI-Reviewed-by` is dropped |
| A2 review by a new session | A1 context-free check | A2 if the reviewer is a different, capable model |
| A3 extensive review or benchmark by a different model | A3 validated by a different model | lower it to A2 if the reviewer only read and produced nothing new |

Two built-in rules are gone: G1–G3 no longer need an AI review, and G0 content can have any level. In `[policy]`, `ai = "A1"` becomes `"A0"` and `ai = "A2"` becomes `"A1"`; for G0, where A1 meant a new session, both become `"A1"`.

Raising the version you pin changes nothing by itself. aisignoff reads `SIGNOFF.toml` with `version = 3` as before and takes its levels over with this table: those of the file, of commit messages and pull request descriptions (so the old pull request template keeps working). A description with the ticked boxes of today's template is read on today's scale already, so the template can change first. Reports show today's levels, and `lint` adds a note. `annotate` and `attest` refuse until the file is version 4.

Change over in one pull request per repository, once your workflows pin 1.0.0rc6 or later (0.15.0 is later: see [Versions](compatibility.md#versions)):

1. **Convert the file** with [`convert-to-version-4.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/convert-to-version-4.py): `python convert-to-version-4.py` at the repository root (`--dry-run` shows the change only). It rewrites the levels and `[policy]` with the table, sets `version = 4`, keeps comments and layout, and writes nothing if the result wouldn't be read as the same declarations. With `[history]`, commit messages can't be rewritten, and from version 4 on their trailers are read on the new scale: for each commit of the default branch whose AI review would read differently, it adds a `[[commits]]` entry with the level as it was meant. The ticked boxes of the old template need none: a landed commit's are read as they were meant.
2. **Change the AI review boxes of the pull request template** in the same pull request, to the wording in [Pull request descriptions](history.md#pull-request-descriptions). With version 4, a ticked A1 box that still says "checked its own work" is an error. Do the same for the issue form of the signoff request, if you use it.
3. **Look at each A3:** it now says that the reviewer produced new evidence and left a record.

The pull request that changes over is read on the scale of the default branch, like any rule of that branch: trailers on the old scale, and the ticked boxes of today's template on today's. Replace the AI review boxes in its description with the new ones by hand, because GitHub fills in the template of the default branch. Since it changes `version`, which sets the scale, a maintainer lands it: on the default branch directly, or with `--allow-policy-change` ([Checking the pull request description](ci.md#checking-the-pull-request-description)). The check fails a change to version 4 that leaves the level of an existing entry as it was written, because that would raise it. It compares the level each file gets, so it also finds an entry whose path is written another way.

After the change, commits that land from branches opened before it are read on the new scale. Correct those with a `[[commits]]` entry.

## From 0.11 or earlier, with `[history]`

0.12 introduced [one owner per line](history.md#one-owner-per-line): a review declared by a commit inside a pull request, or by a pull request merged into another one, no longer counts. Some lines of existing code can report other levels after the upgrade. To keep what 0.11 reported, write what 0.11 says with [`freeze-from-0.11.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/freeze-from-0.11.py), then turn it into `[[commits]]` entries with [`unfreeze.py`](#to-017-no-snapshots) and the current aisignoff:

```bash
git switch -c keep-0.11 origin/main
uv run --no-project --with aisignoff==0.11.0 python freeze-from-0.11.py   # writes SIGNOFF.snapshot.json
python unfreeze.py                                                        # with the current aisignoff
git add SIGNOFF.toml && git commit -m "Keep the declarations of 0.11"
```

Without it, run `aisignoff lint` after upgrading and settle what it reports: move `[[commits]]` review entries for commits inside pull requests to the merge commit (or attest the file), and declare merged templates without a ticked generation or human review box with a `[[commits]]` entry.

## From aidecl, or format version 1 or 2

aisignoff reads only `SIGNOFF.toml` with `version = 4` or `3`. `AIDECL.toml` (the name up to aidecl 0.3.0), format version 1 (one verification axis, `AI-Verification: V0`–`V3`, `Tested-by`, `Verified-by`) and format version 2 (the AI review scale `A-`, `A0`–`A3`, which moved up by one) are no longer read since 1.0.0rc2: `lint` stops with an error for `AIDECL.toml` and old versions of `SIGNOFF.toml`.

Convert such a repository once with 1.0.0rc1, the last release with `aisignoff migrate`, then raise the version you pin:

```bash
uvx aisignoff==1.0.0rc1 migrate --dry-run   # or: pipx run aisignoff==1.0.0rc1 migrate --dry-run
uvx aisignoff==1.0.0rc1 migrate
git add -A SIGNOFF.toml AIDECL.toml         # both sides of the rename, if there was one
```

It renames `AIDECL.toml` to `SIGNOFF.toml` and converts versions 1 and 2, keeping comments and layout for version 2. A repository with only inline tags on the version-2 scale needs `migrate --from 2`. What the old levels don't say, such as the human review of a V1 file, is marked `TODO`, which `lint` reports until a person fills it in. The [documentation of 1.0.0rc1](https://github.com/industrial-mathematics-group/aisignoff/blob/v1.0.0rc1/docs/migrating.md) has the full conversion tables.

Projects renamed from aidecl also switch the badge URLs to `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json`.
