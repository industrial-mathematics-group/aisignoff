# Line by line

`SIGNOFF.toml` and inline tags declare whole files. With `[history]`, aisignoff declares **each line** instead, from git: a line takes the declaration of the commit that brought it in, so a pull request that changes 35 lines of a 800-line file changes the levels of those 35 lines, not of the whole file.

```toml
version = 3

[history]
enabled = true
```

Nothing else has to change. Lines without a declaration from git keep the file-level declaration, so a repository whose commits carry no trailers yet reports exactly what it did before; lines become more precise as declared commits land.

## Where a line's levels come from

For each axis, the newest of these wins:

1. **The commit that landed the line.** Its message carries the levels as [git trailers](#declaring-commits). `git blame --first-parent` finds that commit on the current branch: for a pull request, the squash commit or the merge commit, so the pull request's declaration covers all its lines. For a merge commit, the commits of the merged branch fill the axes it leaves out.
2. **An attestation of the file** whose checked content already contained the line: "this whole file was reviewed, as it was then". See [Re-declaring a whole file](#re-declaring-a-whole-file).
3. **Otherwise, the file-level declaration**: the matching annotation in `SIGNOFF.toml`, or the file's inline tags.

The axes stay separate. Generation follows the line: it only changes when the line changes. A review (human or AI) can be raised for a whole file by an attestation, without touching generation.

For example, a 200-line `solver.py`:

| Step | Result |
|---|---|
| A pull request adds the file, declared G0 H2 A0 | 200 lines G0 H2 A0 |
| Another one rewrites 100 lines, declared G2 H1 A1 | 100 lines G0 H2 A0, 100 lines G2 H1 A1 |
| `aisignoff attest solver.py -H H2 --reviewed-by "Jane Doe"` | 100 lines G0 H2 A0, 100 lines G2 **H2** A1 |
| A third one changes 10 lines, declared G2 H1 A1 | those 10 lines are back to H1, the other 190 stay H2 |

## Declaring commits

A commit declares its lines with trailers, the last paragraph of its message, using the same keys as `SIGNOFF.toml`:

```
Add the folder report

AI-Generation: G3
Human-Review: H1
AI-Review: A1
Assisted-by: Claude Opus 5.5 (Anthropic)
Reviewed-by: Jane Doe
AI-Reviewed-by: Claude Opus 5.5 (Anthropic), self-check by the generating session
```

- **An axis counts when its level is there.** A name on its own, such as the common `Reviewed-by:` trailer without `Human-Review:`, declares nothing.
- **Pull requests:** set *Settings → General → Pull Requests → Default commit message* to **Pull request title and description** for squash (and merge) commits, and put the trailer lines at the end of the pull request description. The declaration then lands in git with the code.
- **TODO** works as in `SIGNOFF.toml`: `lint` reports it until it's filled in.

### Correcting a commit

The history of the default branch isn't rewritten, so a missing or wrong trailer is corrected in `SIGNOFF.toml`, per axis:

```toml
[[commits]]
commit = "6686c01"           # at least 4 hex digits
Human-Review = "H2"          # reviewed after the merge
Reviewed-by = "Jane Doe"
```

The same works for old commits without trailers ("backfilling").

## Re-declaring a whole file

After reviewing a whole file, attest it:

```bash
aisignoff attest src/solver.py -H H2 --reviewed-by "Jane Doe"
aisignoff attest src/ -a A2 --ai-reviewed-by "GPT-5 (OpenAI), fresh session"   # every file below src/
```

This appends one entry per file to `SIGNOFF.toml`, with the git blob hash of the content you checked:

```toml
[[attestations]]
path = "src/solver.py"
blob = "3f1c9e0d5b6a7c8e9f0a1b2c3d4e5f6a7b8c9d0e"
Human-Review = "H2"
Reviewed-by = "Jane Doe"
```

- **It covers the lines that content had.** Lines changed afterwards fall back to the declaration of their own commit. So an attestation never covers code written after the review, and can stay in the file.
- **Content, not commits.** The blob survives a squash merge and renames, unlike a commit hash. Commit the attestation in the same pull request as the review, or later.
- **It checks itself.** If the file changes again before the attested content reaches the branch, `lint` reports that the attestation points at content that never landed: attest again.
- **`--at REV`** attests the files as they were at an earlier commit, e.g. the commit a committed review covered.
- **Generation** can be attested too (`-g`), for corrections; normally an attestation only raises the review axes.

## Requiring declared commits

```toml
[history]
enabled = true
require-trailers-since = "a1b2c3d"
```

Lines of commits after `a1b2c3d` must be declared by their commit (trailers, `[[commits]]` or an attestation); `lint` fails instead of falling back to the file-level declaration. This catches a forgotten pull request template or squash setting. The merge preview that a pull request's CI run checks out is exempt, since the pull request isn't merged yet.

## Showing a change: `aisignoff diff`

```bash
aisignoff diff origin/main
```

```
Changes since origin/main (6686c01): +412 −38 lines in 9 file(s)

       +lines  -lines  Generation (added)  Human review (added)  AI review (added)
docs/     +95     -12  G3 +95              H1 +95                A1 +95
src/     +317     -26  G3 +317             H1 +317               A1 +317

Attested:
  src/aisignoff/model.py  H2

Whole repository, by lines:
  Human review: H1 69.0% → 66.6% (-2.4) · H2 31.0% → 33.4% (+2.4)
```

Like a coverage diff, it shows only what changed: the levels of the added lines (now), of the removed lines (at the base, in `--json`), the attestations the change adds, and how the shares of the whole repository move. It compares the working tree, so it also works before committing.

| Option | Effect |
|---|---|
| `--depth N` | Group by folders down to depth `N` (default 1) |
| `--files` | One row per file |
| `--markdown` | A Markdown table, e.g. for the job summary of a pull request |
| `--json` | Everything, including the levels of the removed lines |
| `-g`, `-H`, `-a` and the name options | Declare the change: lines after the base without a declaration of their own take these levels |

The last row is for pull requests: before the merge, their lines have no squash commit yet, so a workflow can pass the levels from the pull request description. [`signoff-pr-diff.yml`](integration.md) does that.

## Where history isn't available

- **Outside a git repository** and in **shallow clones** (the default of `actions/checkout`), aisignoff warns and uses the file-level declarations. In CI, check out with `fetch-depth: 0`.
- **Binary and empty files** have no lines: the whole file takes the declaration of the commit that last changed it.
- **`precedence = "override"`** on an annotation keeps its files file level, e.g. for vendored or generated code.
- **Reformatting commits** would take over every line they touch. List them in `.git-blame-ignore-revs` (used automatically, or set `ignore-revs-file` in `[history]`); whitespace-only changes are ignored anyway.
