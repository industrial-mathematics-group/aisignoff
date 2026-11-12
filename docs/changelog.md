# Changelog

What changed in each release. Changes that can break a workflow are marked **Breaking**; see [Compatibility](compatibility.md) for what counts.

## 0.14.0

- A second snapshot no longer fails `lint` when a line moved, or came back as it was, between the two. `lint` now checks a changed `SIGNOFF.snapshot.json` by [working it out again](snapshots.md) at its commit, in a temporary worktree, instead of comparing it with the snapshot before it. This catches any hand edit, including names, new lines and the archive.
- New `aisignoff freeze --check` runs that check on its own.
- New `aisignoff freeze --reset FILE...` works files out from history again instead of keeping their frozen levels: to correct a frozen generation with a `[[commits]]` entry, or to apply a changed annotation. It replaces removing a file's entry from the snapshot by hand, which `lint` now rejects.
- The `[[commits]]` and `[[attestations]]` entries that `freeze --prune` archived count wherever levels are worked out from history: files the snapshot doesn't have (also ones included later), files worked out again, and files whose blob doesn't match.
- `--landed` on a release branch that merged the default branch keeps the levels of the lines that came from it, instead of giving them to the merge.
- `lint` notes `[[commits]]` entries for commits from before the snapshot, which change no frozen line by themselves.
- Smaller fixes: `freeze --prune` keeps the comment above the next table; a partial `[[commits]]` entry for a commit that declares nothing says how to raise a review with `attest`; the warning about undeclared pull requests names `aisignoff freeze --allow-warnings`.

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
