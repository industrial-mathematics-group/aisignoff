# Changelog

What changed in each release. Changes that can break a workflow are marked **Breaking**; see [Compatibility](compatibility.md) for what counts.

## 1.0.0rc7

aisignoff now takes everything it knows from `SIGNOFF.toml` and from git (commit messages, pull request descriptions, blame), and never from the content of a file. That ends two things: the report check of 1.0.0rc6, which read the findings out of review reports, and inline tags. See [Upgrading](migrating.md#to-100rc7-no-declarations-in-files).

- A ticked human review box above an unticked one is no longer an error in the check before the merge (it was since 1.0.0rc6): the highest ticked box counts, as for the other axes.
- **Breaking:** inline tags (a declaration in a header comment of the file) are no longer read, and `annotate --inline` is gone. Move them into `SIGNOFF.toml` with `examples/inline-tags-to-toml.py`, run with 1.0.0rc6, before you upgrade. The source `inline` no longer appears in reports.
- **Breaking:** `lint` no longer reads review reports, and the `reports` key of `[review]` is gone (an unknown key now: a warning). How a report looks, and whether it is in order, is up to the repository; `examples/review-report.md` is a template to start from, with problems outside the change kept in a section of their own.
- **Breaking:** a commit message or pull request description gives the highest severity that a review found in the change itself in a line `AI-Review-Findings:` (`none`, `trivial`, `minor`, `major` or `critical`). In the check before the merge, A2 and A3 need it. A severity from `[review]` `recheck` on fails, also in a landed commit: such a finding needs a new review.
- **Breaking:** in the check before the merge, A2 and A3 need their report attached: `AI-Reviewed-by` names a file that is in the change, or a link.
- **Breaking:** a pull request can't change `[review]` or `version` of `SIGNOFF.toml` any more, as it can't change `[policy]`: the base branch's `recheck` applies, and `--allow-policy-change` covers both. A change to version 4 that leaves the AI review of an existing entry as it was written fails in any case, since it would raise that level without a review.
- **Breaking:** model names are compared by their words, without vendor and version, for "A2 and A3 need a different model": `Claude Opus 5.5 (Anthropic), new session` and `Opus` are the model that `Claude Opus (Anthropic)` wrote with. Before, only the same text counted, which the names of the template's model boxes almost never were. "Same session" and "generating session" count as a self-check.
- A repository with `version = 3` reads the ticked boxes of today's pull request template on today's scale, so the template can change before the repository changes over. Before, its A1 box was read as A0.
- Fixed: a model name typed after `Model:` that contained "selfcheck" made the box count as the old template's.
- Fixed: `convert-to-version-4.py` no longer lists files with inline tags. Fixed: it refused a file with `#` or `]` inside a reviewer's name, or stopped with a traceback.

## 1.0.0rc6

The AI review scale changes, so that both review scales are cumulative and the AI review counts only review that is independent of the session that wrote the content ([Levels and rules](levels.md), with definitions for code and for research and writing). Existing repositories keep working and keep their levels: [Upgrading](migrating.md#to-signofftoml-version-4-the-ai-review-scale-of-100rc6).

- **Breaking:** the AI review levels mean something else. **A0** is no independent AI review (the self-check of the generating session is part of generating), **A1** a context-free check by a new session, **A2** that check by a different, capable model, with one committed review report, **A3** a validation by a different, capable model with new evidence, committed with the report. Before, A1 was the self-check, A2 the new session and A3 an extensive review by a different model.
- **Breaking:** `SIGNOFF.toml` is `version = 4`. A file with `version = 3` is still read, as the scale before: its levels, and those of inline tags, commit messages, pull request descriptions and snapshots of earlier rules, are taken over (A1 to A0 without a reviewer, A2 to A1), and `lint` adds a note. `annotate` and `attest` refuse until the file is converted, with the new `examples/convert-to-version-4.py`. Snapshots are written under rules 2.
- **Breaking:** the built-in rules "G1–G3 need at least A1" and "G0 can't be A1" are gone, and with them the special cases of `[policy]` (A1 for G0 meant A2) and of lines (A1 didn't reach hand-written lines). A policy minimum now means the same for every generation level.
- **Breaking:** `lint` fails on A1–A3 whose `AI-Reviewed-by` names only a self-check, on A2 or A3 whose `AI-Reviewed-by` names only models from `Assisted-by`, and, with version 4, on a ticked A1 box of the old pull request template.
- **Breaking:** in the check before the merge (`lint --declare-from`, with version 4), a ticked human review box above an unticked one is an error: the levels build on each other.
- **Breaking:** the `"*"` minimum of `[policy]` also applies to a declaration whose generation is missing or `TODO`. Before, such a declaration was checked against no minimum.
- Fixed: an attestation could lower a review. For lines whose commit declares nothing, an attestation replaced the review of the file-level declaration, also with a lower one. Now the higher counts.
- New `[review]` table with `recheck` (default `"major"`): the severity from which a review's finding needs a new review after its fix, on a scale of trivial, minor, major and critical defined in [When a review counts](levels.md#when-a-review-counts).
- **Breaking:** `lint` fails on a committed review report (`[review]` `reports`, by default the Markdown files in `reviews/`) that lists a finding from that severity on: the finding is fixed, the change reviewed again, and the new report replaces the old one. A report lists its findings as list items or headings that start with the severity, such as `- **minor:** …`.
- In a ticked template, A2 and A3 need the reviewing model after `Model:`; A1 without one names the models that wrote the change, as a new session.
- The issue form of the signoff request and the `@signoff` assistant use the new wording. The assistant's pull requests declare G1 with A0.
- New example: the `@signoff` assistant (`signoff-assistant.yml`), which turns a request in plain words in an issue or comment into the answers of the signoff request form with the Claude API, asks in a comment for what is missing, and hands complete answers to `signoff-request.yml`, which now also runs through `workflow_call` ([The @signoff assistant](ci.md#the-signoff-assistant)). Optional: needs the secret `ANTHROPIC_API_KEY`.

## 1.0.0rc5

- **Breaking:** `lint` checks every `[[commits]]` entry against the built-in rules and the `[policy]`, as the declaration of its commit corrected by the entry, also when that commit owns no line that is checked. Before, an entry was only checked through the lines it owns, so one for a commit that changed only `SIGNOFF.toml`, or whose lines are gone, passed whatever it said (seen in a signoff request that recorded G3/H0/A1 under a policy that needs H1 and A2 for G3).

## 1.0.0rc4

- **Breaking:** with `--allow-policy-change`, the pull request is still checked under the base branch's `[policy]`, not its own, so a pull request can't lower the bar for itself; the new policy applies to the pull requests after it. In 1.0.0rc3 a maintainer's pull request that lowered the policy was checked under the lowered one and passed.
- With `--allow-policy-change`, `lint` says that the change alters `[policy]`, `exclude` or `[history]`, or removes `SIGNOFF.toml`, instead of saying nothing.

## 1.0.0rc3

`lint --declare-from` becomes the whole check of a pull request before its merge, so a separate check of the description isn't needed ([Checking the pull request description](ci.md#checking-the-pull-request-description)). How landed commits are read is unchanged.

- **Breaking:** with `--declare-from`, the description must be complete on its own (levels, names, built-in rules, policy), also for a pull request that changes no declared line, such as one that changes only `SIGNOFF.toml`.
- **Breaking:** with `--base`, the base branch's `[policy]` applies, and a change to `[policy]`, `exclude` or `[history]`, or removing `SIGNOFF.toml`, fails unless `--allow-policy-change` is given.
- A pull request opened by a bot (`--author` ending in `[bot]`) must name a human with `Responsible person: @login`, who is then the reviewer.
- In a repository without `SIGNOFF.toml`, `lint --declare-from` checks the description alone.
- `report --json --declare-from` adds `pull_request`: what the description declares and what is wrong with it.
- New example: an issue form and workflow that turn a request into a pull request that changes `SIGNOFF.toml`, written with `annotate` or `attest` or as a `[[commits]]` entry, for the requester to review and merge, without AI, as `github-actions[bot]` or your own GitHub App ([Signoff requests from issues](ci.md#signoff-requests-from-issues)).

## 1.0.0rc2

Removes what was kept for repositories from before version 3 of the format, so 1.0 reads only the current one. Allowed in a release candidate by the [compatibility](compatibility.md) promise, which starts with 1.0.0.

- **Breaking:** `aisignoff migrate` is gone. Convert old repositories once with `uvx aisignoff==1.0.0rc1 migrate` before upgrading ([Upgrading](migrating.md#from-aidecl-or-format-version-1-or-2)).
- **Breaking:** `AIDECL.toml` is no longer read in place of `SIGNOFF.toml`. While one exists, every command stops with an error that says how to convert it.
- **Breaking:** inline tags of format version 1 (`AI-Verification`, `Tested-by`, `Verified-by`) are no longer recognised, so a file tagged only with them has no inline declaration.
- `SIGNOFF.toml` of versions 1 and 2 and the old level `A-` get the plain errors for an unsupported version and an invalid level, pointing to 1.0.0rc1 instead of `migrate`.

## 1.0.0rc1

The first release candidate for 1.0. It fixes what the 1.0 readiness review found; 1.0.0 is meant to follow from the same code once it has run unchanged for a while.

- A snapshot records the `"rules"` it was written under: a number raised only by a release that changes the levels some line gets. A snapshot of other rules, such as one written by 0.11 to 0.13, is accepted as it is on the default branch (`freeze --check` notes it, instead of failing), and fails as a change. Archives compare with full commit hashes, so 0.13's short ones pass. Land a snapshot of an older version before raising the version CI pins ([Migrating](migrating.md#from-011-or-earlier-with-history)).
- **Breaking:** an unknown top-level or `[history]` key in `SIGNOFF.toml` is a warning instead of an error, so a setting of a later 1.x doesn't stop an older install (`lint --strict` fails on it).
- **Breaking:** `lint` fails in a shallow clone when `[history]` is enabled, instead of falling back to the file-level declarations: a checkout without `fetch-depth: 0` would pass without the line-by-line check.
- In CI, the default branch is also found by the name GitHub Actions' event gives. When none is found, `lint --declare-from`, `--base` and `--landed` fail instead of checking nothing.
- A commit on a pull request's branch that says only a higher `AI-Generation` takes the model the pull request names. When nothing names one, the error names the commit.
- On the default branch, a snapshot deleted or put back to an older one fails `lint` against the commit below (and every commit of the push on GitHub Actions).
- `lint` warns about an entry of `.git-blame-ignore-revs` that declares levels, is a merge or looks like a pull request, and about a pull request merged into another one whose description declares a higher `AI-Generation` than the outer one.
- `freeze` refuses a commit that isn't on `origin`'s default branch yet, and says which earlier `--reset` files a second run before committing leaves frozen.
- `report --json | head` no longer prints a traceback. git runs with `LC_ALL=C`.
- The keys of the `--json` outputs are [documented](report.md#json-output) and pinned by a test.
- This repository's snapshot is written again under the current rules.

## 0.14.0

- A second snapshot no longer fails `lint` when a line moved, or came back as it was, between the two. `lint` now checks a changed `SIGNOFF.snapshot.json` by [working it out again](snapshots.md) at its commit, in a temporary worktree, instead of comparing it with the snapshot before it. This catches any hand edit, including names, new lines and the archive.
- New `aisignoff freeze --check` runs that check on its own.
- New `aisignoff freeze --reset FILE...` works files out from history again instead of keeping their frozen levels: to correct a frozen generation with a `[[commits]]` entry, or to apply a changed annotation. It replaces removing a file's entry from the snapshot by hand, which `lint` now rejects.
- The `[[commits]]` and `[[attestations]]` entries that `freeze --prune` archived count wherever levels are worked out from history: files the snapshot doesn't have (also ones included later), files worked out again, and files whose blob doesn't match.
- `--landed` on a release branch that merged the default branch keeps the levels of the lines that came from it, instead of giving them to the merge.
- `lint` notes `[[commits]]` entries for commits from before the snapshot, which change no frozen line by themselves.
- Smaller fixes: `freeze --prune` keeps the comment above the next table; a partial `[[commits]]` entry for a commit that declares nothing says how to raise a review with `attest`; the warning about undeclared pull requests names `aisignoff freeze --allow-warnings`.
- The check compares levels and names, and checks a snapshot whatever version wrote it: another version that works levels out differently fails. A snapshot that can't be checked fails too, also in `freeze --check`.
- A changed snapshot can't go back: an older commit than the default branch's snapshot, or dropped archived entries (by an older snapshot put back, a deleted one, or one taken afresh) fail `lint`.
- git runs with the settings that change levels pinned, and blame clears a personal `blame.ignoreRevsFile`, so a personal git config can't make an honest snapshot fail the check.
- `freeze --prune` archives each commit with its full hash; an archived hash that is ambiguous is reported.
- On GitHub Actions, a snapshot changed by any commit of a push is checked, not only by the last one.
- `freeze` can run again before the snapshot is committed, and starts from the committed one.
- The note about `[[commits]]` entries from before the snapshot counts only entries added since it was taken.

## 0.13.0

- **Breaking:** an attestation records reviews only. `attest -g` is gone, and an `AI-Generation` in an existing `[[attestations]]` entry no longer counts (`lint` warns). Correct the generation of a commit with a `[[commits]]` entry.
- New `aisignoff freeze --prune` moves the `[[commits]]` and `[[attestations]]` entries of `SIGNOFF.toml` into an `archive` in `SIGNOFF.snapshot.json`: [the snapshot has their levels](snapshots.md), so `SIGNOFF.toml` starts afresh after each freeze.
- `lint` fails when a snapshot changes lines that the snapshot before it already had, other than raising a review that an attestation gives. This catches a snapshot edited by hand.
- `lint` warns about commits that look like pull requests ("Merge pull request #12 …", "… (#12)") and declare nothing, in one line (`--strict` fails).

## 0.12.0

- **Breaking:** [one owner per line](history.md#one-owner-per-line). The commit that lands a line on the default branch (a direct commit, a squash commit, or a pull request's merge commit) declares it. Commits and pull requests inside it no longer declare reviews. A commit inside a merge can still say a higher `AI-Generation` for its lines; a lower one, such as G0 in a pull request declared G3, needs a `[[commits]]` entry, since it takes the AI review requirement off the lines. This replaces "generation from the most specific declaration, reviews from the highest" of 0.10, the warnings about raised reviews, and the special handling of pull requests merged into each other. See [Upgrading](migrating.md#from-011-or-earlier-with-history) to keep the levels of existing code.
- New [`aisignoff freeze`](snapshots.md) writes `SIGNOFF.snapshot.json`, the levels of every line as of a commit of the default branch. Lines that don't change keep them, whatever later versions or settings would work out, and history is only read from that commit on.
- **Breaking:** lines that aren't on the default branch yet (a feature branch, a pull request's merge preview, uncommitted changes) are the diff against it, and fail nothing on their own. Without a declaration for the change they show the generation their commits say, and their reviews as undeclared. The merge preview is no longer recognised by its subject and `GITHUB_EVENT_NAME`. New setting `default-branch` in `[history]`.
- New `lint --declare-from FILE`, `report --declare-from FILE` and `diff --declare-from FILE` read a pull request description as its merge or squash commit's message will be read; `lint` then checks that it is complete. `diff` accepts `TODO` levels. A declaration for a pull request into another branch than the default one isn't applied. [`signoff-pr-diff.yml`](ci.md#example-workflows) no longer imports aisignoff's Python modules.
- **Breaking:** a pull request template with no generation or human review box ticked, and a level line left empty (`Human-Review:`), are a `TODO` that `lint` reports, instead of silently taking the file-level declaration.
- New setting `undeclared = "error"` in `[history]`: every commit that lands lines on the default branch must declare them.
- New `--landed` for `lint`, `report` and `badge`: `HEAD` is checked as a commit of the default branch. A merge queue's run on GitHub Actions (`merge_group`) is recognised by itself, so the commit that will land is checked as in 0.11; release branches need the option.
- **Breaking:** `report`, `diff` and the badges count "undeclared" per axis. An error about one axis (a missing `AI-Reviewed-by`, a `TODO` human review, a level below the policy) no longer makes the other two axes undeclared. The numbers of repositories with invalid declarations change accordingly.
- `attest --at REV` of content from before the snapshot raises the frozen lines that content had. `attest` refuses a file declared with `precedence = "override"`, where it had no effect.
- `freeze` refuses when `lint` has warnings (`--allow-warnings` overrides) and prints what stands in its way. `lint` also fails when a snapshot's runs don't cover a file's lines. Files the snapshot doesn't have are resolved from history.
- `lint` warns about reverts (also through a pull request) and `git pull` merges that own lines without declaring them, and about `[[commits]]` entries that give a review to a commit inside a pull request (`--strict` fails).
- `report --json` says where each level of a part comes from (`kinds`) and whether the part has landed (`advisory`).
- **Breaking:** the `--json` output of `report` and `diff` starts with `"format": 1` and `"aisignoff"` (the version that wrote it). `report --json` is now an object with the files under `"files"`, instead of a bare list. Change `json.load(f)` to `json.load(f)["files"]`; the [example workflow](ci.md#example-workflows) does this already.
- New [Compatibility](compatibility.md) page: what is meant to stay stable and what may still change.
- This changelog.

## 0.11.0

- [Folder report](report.md): each axis has its own colour ramp, whose hue shifts as it darkens, the same in light and dark mode.
- The review gap is a fourth axis in the sunburst, the line view and the table.
- The new *Average* folder colour is the default: a folder is coloured between the steps by its weighted average level.
- Fixes from the review of 0.10.1.

## 0.10.1

- Fixes from the review of 0.10.0, among them A1 on human-written lines, Markdown that hid a declaration, `diff --declare` on the branch itself, `git log` read NUL-separated, the rebase merge preview and `push` events.
- A review raised by a commit inside a pull request is kept, and `lint` warns about it (`--strict` fails).

## 0.10.0

- Declarations per axis: generation comes from the most specific declaration (attestation, branch commit, inner merge, landing commit), reviews take the highest.
- A commit that declares some axes but leaves one out is an error.
- New settings `merge-method` and `ignore-whitespace` in [`[history]`](history.md).

## 0.9.0

- A merge commit declares the lines of its branch; the branch's own commits override it per axis.
- A commit uses either trailers or checkboxes, not both.

## 0.8.0

- [Line by line](history.md) declarations read the ticked boxes of the pull request template in squash commits, so `SIGNOFF.toml` no longer needs an annotation per pull request.

## 0.7.1

- Fixes from the review of 0.7.0.

## 0.7.0

- Line view in the HTML report: `--with-source` embeds the files, `--since BASE` marks what changed.

## 0.6.0

- [Line by line](history.md) declarations from git history: `[history]`, commit trailers, `[[commits]]` and `[[attestations]]`.
- New commands `attest` and `diff`.

## 0.5.0

- [Folder report](report.md): `report --tree` and `report --html`.
- [Example workflows](ci.md#example-workflows) and a pre-commit hook.
- Documentation built with Zensical.

## 0.4.x

- Renamed from `aidecl` to aisignoff, with `SIGNOFF.toml` instead of `AIDECL.toml`, and published on PyPI. `aisignoff migrate` renames the old file and converts declarations from versions 1 and 2 of the level scale.
- Documentation site on GitHub Pages.
