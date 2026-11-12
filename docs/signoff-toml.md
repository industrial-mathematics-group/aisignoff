# SIGNOFF.toml

`SIGNOFF.toml` in the repository root declares files by path. Create it with `aisignoff init` and extend it with `aisignoff annotate`, or edit it by hand.

```toml
version = 3

# optional: files that need no declaration
exclude = ["reviews/**", "docs/build/**"]

# optional: minimum levels
[policy]
"*" = { human = "H1" }
G3  = { human = "H2", ai = "A2" }

[[annotations]]
path = "**"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A0"
Reviewed-by = "Jane Doe"

[[annotations]]
path = ["results/**", "figures/*.pdf"]
AI-Generation = "G2"
Human-Review = "H3"
AI-Review = "A3"
Assisted-by = ["Claude Opus 5.5 (Anthropic)"]
AI-Reviewed-by = "GPT-5 (OpenAI), full benchmark against reference solutions"
Reviewed-by = "Jane Doe"
```

## Annotations

- **`path`:** one glob or a list, relative to the repository root.
    - `*` stays within a folder, `**` crosses folders (`**/` also matches no folder), and `?` is one character.
    - `\*`, `\?` and `\\` match those characters literally.
    - This is modelled on `REUSE.toml`, plus `?`.
- **The last matching annotation wins,** so put the general default first and the exceptions after it.
- **`precedence`** (optional): `"closest"` (default) lets [inline tags](inline-tags.md) in a file win; `"override"` makes the annotation win over them.
- **Keys:** the three levels and the names below. `Assisted-by`, `AI-Reviewed-by` and `Reviewed-by` take a string or a list.

Every file needs a valid declaration:

| Key | Required for |
|---|---|
| `AI-Generation`, `Human-Review`, `AI-Review` | every file |
| `Reviewed-by` (the responsible human) | every file |
| `Assisted-by` (the AI models that wrote it) | G1–G3; not allowed for G0 |
| `AI-Reviewed-by` (the AI that reviewed it, and how) | A1–A3; not allowed for A0 |

## Placeholders

Any value may be `"TODO"`, e.g. `Human-Review = "TODO"` when an agent declares its part and a person adds the human review later. aisignoff still checks the axes that are filled in, and `lint` reports every TODO until it's filled in.

## Minimum levels

G1–G3 always need at least **A1**: AI-written content must at least be self-checked. The `[policy]` table can require more:

- **`"*"`** sets the default for every generation level.
- **`G0`–`G3`** refine it per generation level, overriding the `"*"` values key by key.
- **Keys:** `human` (H0–H3) and `ai` (A0–A3).

For G0, a minimum of A1 means A2, since human-written content has no self-check.

## Line by line

Three more tables declare lines instead of files, from git history. They're described in [Line by line](history.md):

```toml
[history]
enabled = true
undeclared = "error"                 # optional

[[commits]]                          # corrects the declaration of a commit
commit = "6686c01"
Human-Review = "H2"
Reviewed-by = "Jane Doe"

[[attestations]]                     # written by 'aisignoff attest'
path = "src/solver.py"
blob = "3f1c9e0d5b6a7c8e9f0a1b2c3d4e5f6a7b8c9d0e"
Human-Review = "H2"
Reviewed-by = "Jane Doe"
```

- **`[history]`:** `enabled` (default `true` once the table is there), `default-branch` (default: `origin`'s default branch, else `main` or `master`), `undeclared` (`"baseline"`, the default: lines of a commit that declares nothing take the file-level declaration; `"error"`: `lint` fails), `require-trailers-since` (a commit: `undeclared = "error"` for the commits after it), `ignore-revs-file` (default: `.git-blame-ignore-revs` if it exists), `merge-method` (`"merge"`, the default, `"squash"` or `"rebase"`: how pull requests land, for the lines of one that isn't merged yet), `ignore-whitespace` (default `true`: `git blame -w`).
- **`[[commits]]` and `[[attestations]]`** take the declaration keys like an annotation, but only whole axes: at least one level, and a name list only next to its level.
- With history, the annotations and inline tags become the fallback for lines that git doesn't declare.
- **`SIGNOFF.snapshot.json`**, next to `SIGNOFF.toml`, is written by [`aisignoff freeze`](history.md#freezing-the-levels-aisignoff-freeze): the levels of every line as of one commit. Don't edit it by hand.

## Which files are checked

- **In a git repository:** all tracked files plus untracked files that aren't ignored, so `.gitignore` is respected. If git can't be run there, aisignoff stops with an error rather than ignoring `.gitignore`.
- **Outside git:** every file below the root.
- **Always skipped:** `SIGNOFF.toml` itself (and `AIDECL.toml`, its [old name](migrating.md#from-aidecl)), `SIGNOFF.snapshot.json` and anything under `exclude`.

!!! tip
    Exclude the folder of committed AI reviews (`reviews/` by convention), since the reviews themselves need no declaration.
