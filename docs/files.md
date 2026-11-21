# Declaring files

A file's declaration comes from `SIGNOFF.toml`. With [line-level declarations](history.md), this file-level declaration is the fallback for lines that git doesn't declare. aisignoff never reads the content of a file for a declaration: everything it knows comes from `SIGNOFF.toml` and from git.

## Annotations in SIGNOFF.toml

`SIGNOFF.toml` in the repository root maps paths to declarations:

```toml
version = 4
exclude = ["reviews/**"]

[[annotations]]
path = "**"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A0"
Reviewed-by = "Jane Doe"

[[annotations]]
path = ["results/**", "figures/*.pdf"]
AI-Generation = "G2"
Human-Review = "H1"
AI-Review = "A1"
Assisted-by = "Claude Opus 5.5 (Anthropic)"
AI-Reviewed-by = "Claude Opus 5.5 (Anthropic), new session without the generating conversation"
Reviewed-by = "Jane Doe"
```

- **The last matching annotation wins.** Put the general default first and the exceptions after it.
- **`path`** is one glob or a list, relative to the repository root. `*` stays within a folder, `**` crosses folders (`**/` also matches no folder), `?` is one character, and `\*`, `\?`, `\\` match those characters literally.
- **Names** (`Assisted-by`, `Reviewed-by`, `AI-Reviewed-by`) take a string or a list.
- **`precedence`** decides between the annotation and git history, [below](#which-one-wins).

Write annotations by hand or with `aisignoff annotate`:

```bash
aisignoff annotate results/ -g G2 -H H1 -a A1 \
    --assisted-by "Claude Opus 5.5 (Anthropic)" \
    --ai-reviewed-by "Claude Opus 5.5 (Anthropic), new session without the generating conversation" \
    --reviewed-by "Jane Doe"
```

Each call appends one annotation for all the paths it's given. It refuses an incomplete declaration or one below the [policy](levels.md#minimum-levels), and leaves `SIGNOFF.toml` unchanged if the result wouldn't be valid. Existing files are matched exactly (even with `*` in their name), a folder becomes `folder/**`, and anything else is a glob, which must be quoted and is read relative to the current directory. Paths outside the project are refused.

## Which one wins

Without `[history]`, the annotation is the file's declaration. With it, by default (`precedence = "closest"`), each line is declared by the commit that wrote it, and the annotation declares the lines whose commits declare nothing.

With `precedence = "override"` on the annotation, the annotation alone counts: such files are never resolved line by line, which suits vendored or generated code.

!!! note "Inline tags"
    Up to 1.0.0rc6, a file could also declare itself in a header comment (`# AI-Generation: G2`). These tags are no longer read: [move them into `SIGNOFF.toml`](migrating.md#to-100rc7-no-declarations-in-files).

## What aisignoff reads

Declarations come from two places only: `SIGNOFF.toml` and git, that is commit messages, the pull request description passed to [`lint --declare-from`](ci.md#checking-the-pull-request-description), diffs and blame. Nothing in the content of a file can declare, raise or lower anything.

The files themselves are opened for three things, none of which reads a declaration: to count their lines (and to see that a file is binary), to show their text in the [folder report](report.md#the-interactive-report) with `--with-source`, and to pass `.git-blame-ignore-revs` on to git.

## Which files are checked

- **In a git repository:** tracked files plus untracked files that aren't ignored, so `.gitignore` is respected. If git can't be run there, aisignoff stops rather than ignoring `.gitignore`.
- **Outside git:** every file below the root.
- **Never:** `SIGNOFF.toml` itself, a `SIGNOFF.snapshot.json` left from 0.16 or earlier, and anything that matches `exclude`.

!!! tip
    Exclude the folder of committed AI reviews (`reviews/` by convention): the reviews need no declaration themselves.
