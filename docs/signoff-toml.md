# SIGNOFF.toml reference

`SIGNOFF.toml` sits in the repository root. It is the file a person signs off: the rules, the annotations, a person's reviews and the corrections of a commit. AI reviews go into the [review folder](history.md#the-review-folder) instead ([Who writes what](#who-writes-what)). Every key below is optional except `version`. An invalid level, a malformed table, a file that isn't UTF-8 or can't be read, and an unknown key anywhere are configuration errors (exit code `2`). Every key changes what the file means, so an unknown one is never ignored: it is a typo, or a key of a newer aisignoff, for which the repository sets `requires-aisignoff`.

A pull request that removes an unknown key from the default branch's `SIGNOFF.toml` fails the [check before the merge](ci.md#checking-the-pull-request-description), which reads the default branch's rules: a maintainer merges it past the check, after looking at it closely. (Before raising a workflow's pin to 0.22 or later, a key that only warned so far can still be removed in an ordinary pull request.)

```toml
version = 4
requires-aisignoff = "0.22"
exclude = ["docs/build/**"]   # the review folder (reviews/) is left out by itself

[policy]
"*" = { human = "H1" }
G3  = { human = "H2", ai = "A1" }

[[annotations]]
path = "**"
precedence = "closest"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A0"
Reviewed-by = "Jane Doe"

[history]
enabled = true
default-branch = "main"
merge-method = "merge"
undeclared = "baseline"
require-trailers-since = "1a2b3c4"
ignore-whitespace = true
ignore-revs-file = ".git-blame-ignore-revs"

[[commits]]
commit = "6686c01"
Human-Review = "H2"
Reviewed-by = "Jane Doe"

[[attestations]]
path = "src/solver.py"
blob = "3f1c9e0d5b6a7c8e9f0a1b2c3d4e5f6a7b8c9d0e"
Human-Review = "H2"
Reviewed-by = "Jane Doe"
```

## Who writes what

| | `SIGNOFF.toml` | Record files in the review folder (`reviews/*.toml`) |
|---|---|---|
| Written by | a person, or a workflow a person approves (`attest -H`, `correct`, `annotate`) | AI reviewers (`attest -a`) |
| Holds | everything below | `[[attestations]]` with an AI review (A1–A3) and its findings, nothing else |
| Never holds | | a generation, a human review, `Reviewed-by`, a `[[commits]]` entry |
| Grows | as fast as a person signs off | add-only, one file per review |

- **The owner of a line declares its generation**, in the commit that landed it. A wrong one is a mistake that a person corrects, with a `[[commits]]` entry in `SIGNOFF.toml`.
- **AI reviews count in the order they were recorded,** by the commit of the default branch that recorded them: the one that added the entry to `SIGNOFF.toml` or the record file to the review folder. Neither file counts before the other, so a re-review recorded with `attest --signoff` replaces the findings of an earlier review in the review folder, and the other way round. The later review of the same lines gives their findings, unless the earlier one saw newer content of the file ([The later review counts](history.md#the-review-folder)).
- **An AI review a change adds to `SIGNOFF.toml`** (an `[[attestations]]` entry, or a `[[commits]]` entry that gives `AI-Review`) is checked like a record file: A1–A3 give their findings, and A2 and A3 name their report, a file of the repository or a link. Entries that have landed are read as they are, so a review recorded before findings existed keeps F-.
- **Make it hold on GitHub:** give `SIGNOFF.toml` a code owner and require their review, so that a change to it needs a person's approval. aisignoff can't tell who edited a file.

```text
# .github/CODEOWNERS (with "Require review from Code Owners" in the branch protection or ruleset)
/SIGNOFF.toml  @your-login
```

## Top level

| Key | Value |
|---|---|
| `version` | `4`, required. A higher version is of a newer aisignoff, and a configuration error that says so. `3` is still read, as the AI review scale before 1.0.0rc6 taken over to today's, with a note from `lint`: see [Upgrading](migrating.md#to-signofftoml-version-4-the-ai-review-scale-of-100rc6). Versions 1 and 2 are no longer read |
| `requires-aisignoff` | the oldest aisignoff that understands this file, such as `"0.22"` or `"1.2.3"`: an older one stops with a configuration error that names this release, instead of an unknown key. Set it when the file uses a key that a release added |
| `exclude` | a glob or list of globs: files that need no declaration |

## Declaration keys

Annotations, `[[commits]]` and `[[attestations]]` use the same keys (case-insensitive):

| Key | Value |
|---|---|
| `AI-Generation` | `G0`–`G3` or `"TODO"` |
| `Human-Review` | `H0`–`H3` or `"TODO"` |
| `AI-Review` | `A0`–`A3` or `"TODO"` |
| `Assisted-by`, `Reviewed-by`, `AI-Reviewed-by` | a string or a list of strings |
| `AI-Review-Findings` | `"none"`, `"trivial"`, `"minor"`, `"major"` or `"critical"`: what an AI review of A1, A2 or A3 found, shown as the [findings level](levels.md#findings-f0-to-f3). Only next to `AI-Review`, and only read for A1 to A3 |

What a complete declaration needs is on [Levels and rules](levels.md#what-a-valid-declaration-needs).

## `[policy]`

Minimum levels, keyed by `"*"` (every generation level) or `G0`–`G3` (overriding `"*"` key by key). Each value is a table with `human` (H0–H3) and/or `ai` (A0–A3). See [Minimum levels](levels.md#minimum-levels).

## `[review]`

| Key | Value |
|---|---|
| `dir` | the review folder, relative to the project root: `"reviews"` by default, `""` for none. Its files need no declaration, a change may only add files to it, and the `.toml` files directly in it are record files (those of its subfolders are evidence, never read). A pull request can't change it, like `exclude` ([Who writes what](#who-writes-what)). See [The review folder](history.md#the-review-folder) |

1.0.0rc8 had `[review]` with `recheck`, the severity from which a finding failed `lint`. Findings are now recorded and block nothing ([Findings](levels.md#findings-f0-to-f3)), so `recheck` is no longer read: `lint` warns until it is removed.

## `[[annotations]]`

| Key | Value |
|---|---|
| `path` | a glob or list of globs, required. The last matching annotation wins |
| `precedence` | `"closest"` (default): with `[history]`, the commits that wrote a line declare it, and the annotation declares the rest. `"override"`: the annotation alone counts, and the file is declared as a whole |
| declaration keys | as above |

See [Declaring files](files.md).

## `[history]`

Line-level declarations from git, described in [Declaring lines](history.md).

| Key | Default | Value |
|---|---|---|
| `enabled` | `true` once the table is there | `true` or `false` |
| `default-branch` | `origin`'s default branch, else the one GitHub Actions names, else `main` or `master` | the branch whose commits own the lines; one that isn't here is a configuration error |
| `merge-method` | `"merge"` | `"merge"`, `"squash"` or `"rebase"`: how pull requests land, for checks before the merge |
| `undeclared` | `"baseline"` | `"baseline"`: lines of a commit that declares nothing take the file-level declaration. `"error"`: `lint` fails |
| `require-trailers-since` | none | a commit of the default branch: `undeclared = "error"` for the commits after it only; one that isn't a commit of the default branch is a configuration error |
| `ignore-whitespace` | `true` | `git blame -w`: whitespace-only changes keep a line's owner |
| `ignore-revs-file` | `.git-blame-ignore-revs` if it exists | a file of commits for `git blame` to skip, such as reformatting commits; a file that doesn't exist is a configuration error |

## `[[commits]]`

Declares or corrects the declaration of one commit, axis by axis. See [Correcting a commit](history.md#correcting-a-commit).

| Key | Value |
|---|---|
| `commit` | a commit hash, at least 4 hex digits, required |
| declaration keys | at least one level; a name only next to its level |

[`aisignoff correct`](commands.md#correct) writes one. They belong in `SIGNOFF.toml` only: a record file of the review folder can't hold them.

`lint` checks each entry of `SIGNOFF.toml` as the declaration of its commit (the commit's message, corrected by the entry) against the built-in rules and the `[policy]`, also when the commit owns no line that is checked, such as one that changed only `SIGNOFF.toml`. An axis that neither declares is left out of the check. (`[[attestations]]` only raise reviews, so they can't bring a line below the policy.)

## `[[attestations]]`

Raises the reviews of one file, as of the content that was checked, or of the lines one commit landed. Written by [`aisignoff attest`](commands.md#attest); see [Raising a review](history.md#raising-a-review-attestations).

| Key | Value |
|---|---|
| `blob` | the full git blob hash of the checked content: the entry covers the whole file as it was then. Give `blob` or `commit` |
| `commit` | a commit of the default branch (at least 7 hex digits; `attest` writes the full hash): the entry covers the lines it landed and that are still there ([The lines of one commit](history.md#the-lines-of-one-commit)) |
| `path` | the path of one file (no glob): required with `blob`; optional with `commit`, which without it covers the commit's lines in every file |
| `Human-Review`, `AI-Review` and their names | at least one review level; a name only next to its level. An `AI-Generation` here doesn't count |
| `AI-Review-Findings` | with `AI-Review` A1, A2 or A3: what that review found, for every line the entry covers (`aisignoff attest --findings`) |

The same tables make up the record files of the [review folder](history.md#the-review-folder), where they give only `AI-Review` (A1–A3), `AI-Reviewed-by` and `AI-Review-Findings`.

An entry whose file was deleted, or whose lines have all changed since, covers no line any more. That is no error: `lint` notes it, and [`aisignoff gc`](commands.md#gc) deletes it.

## SIGNOFF.snapshot.json

Written by `aisignoff freeze` up to 0.16. Since 0.17 it is no longer read, and `lint` fails while it is there: move what it says into `SIGNOFF.toml` with [`unfreeze.py`](migrating.md#to-017-no-snapshots) and delete it.
