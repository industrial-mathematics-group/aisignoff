# SIGNOFF.toml reference

`SIGNOFF.toml` sits in the repository root. Every key below is optional except `version`. An unknown key, an invalid level or a malformed table is a configuration error (exit code `2`).

```toml
version = 3
exclude = ["reviews/**"]

[policy]
"*" = { human = "H1" }
G3  = { human = "H2", ai = "A2" }

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

## Top level

| Key | Value |
|---|---|
| `version` | `3`, required. Versions 1 and 2 are no longer read; see [Upgrading](migrating.md#from-aidecl-or-format-version-1-or-2) |
| `exclude` | a glob or list of globs: files that need no declaration |

## Declaration keys

Annotations, `[[commits]]` and `[[attestations]]` use the same keys (case-insensitive):

| Key | Value |
|---|---|
| `AI-Generation` | `G0`–`G3` or `"TODO"` |
| `Human-Review` | `H0`–`H3` or `"TODO"` |
| `AI-Review` | `A0`–`A3` or `"TODO"` |
| `Assisted-by`, `Reviewed-by`, `AI-Reviewed-by` | a string or a list of strings |

What a complete declaration needs is on [Levels and rules](levels.md#what-a-valid-declaration-needs).

## `[policy]`

Minimum levels, keyed by `"*"` (every generation level) or `G0`–`G3` (overriding `"*"` key by key). Each value is a table with `human` (H0–H3) and/or `ai` (A0–A3). See [Minimum levels](levels.md#minimum-levels).

## `[[annotations]]`

| Key | Value |
|---|---|
| `path` | a glob or list of globs, required. The last matching annotation wins |
| `precedence` | `"closest"` (default): inline tags win per axis. `"override"`: the annotation alone counts, and with `[history]` the file is declared as a whole |
| declaration keys | as above |

See [Declaring files](files.md).

## `[history]`

Line-level declarations from git, described in [Declaring lines](history.md).

| Key | Default | Value |
|---|---|---|
| `enabled` | `true` once the table is there | `true` or `false` |
| `default-branch` | `origin`'s default branch, else the one GitHub Actions names, else `main` or `master` | the branch whose commits own the lines |
| `merge-method` | `"merge"` | `"merge"`, `"squash"` or `"rebase"`: how pull requests land, for checks before the merge |
| `undeclared` | `"baseline"` | `"baseline"`: lines of a commit that declares nothing take the file-level declaration. `"error"`: `lint` fails |
| `require-trailers-since` | none | a commit of the default branch: `undeclared = "error"` for the commits after it only |
| `ignore-whitespace` | `true` | `git blame -w`: whitespace-only changes keep a line's owner |
| `ignore-revs-file` | `.git-blame-ignore-revs` if it exists | a file of commits for `git blame` to skip, such as reformatting commits |

## `[[commits]]`

Declares or corrects the declaration of one commit, axis by axis. See [Correcting a commit](history.md#correcting-a-commit).

| Key | Value |
|---|---|
| `commit` | a commit hash, at least 4 hex digits, required |
| declaration keys | at least one level; a name only next to its level |

## `[[attestations]]`

Raises the reviews of one file, as of the content that was checked. Written by [`aisignoff attest`](commands.md#attest); see [Raising a review](history.md#raising-a-review-attestations).

| Key | Value |
|---|---|
| `path` | the path of one file (no glob), required |
| `blob` | the full git blob hash of the checked content, required |
| `Human-Review`, `AI-Review` and their names | at least one review level; a name only next to its level. An `AI-Generation` here doesn't count |

## SIGNOFF.snapshot.json

Written by [`aisignoff freeze`](snapshots.md) next to `SIGNOFF.toml`, format `"format": 1`. Don't edit it by hand: `lint` checks it by working it out again.
