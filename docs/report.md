# Reports

`lint` says whether everything is declared. The reports show what was declared, from one number per axis down to each line.

## Summary: `aisignoff report`

```
$ aisignoff report
2 files, 34 lines, declared line by line

Generation
  G0         Human                                     23   67.6%
  G1         AI-assisted                                1    2.9%
  G3         AI-autonomous                             10   29.4%

Human review
  H2         Reviewed line by line                     34  100.0%

AI review
  A0         No AI review                              23   67.6%
  A1         Self-check by the generating session      11   32.4%
```

The shares count files, or lines with `[history]`. Each axis is counted on its own, with an *undeclared* share for what is missing, `TODO`, invalid or has an error about that axis ([how axes are counted](levels.md#how-reports-count-an-axis)).

- `--files` gives one line per file: its levels (with `[history]`, the share of each combination of levels), where they come from (`SIGNOFF.toml [2]` is the second annotation, `inline` a tag in the file), and any problems.
- `--json` gives the same per file for other tools: `{"format": 1, "aisignoff": VERSION, "files": [...]}`. With `[history]`, each file has `parts`: runs of lines with one declaration, with `kinds` (where each axis comes from) and `advisory` (lines that haven't landed and wait for their pull request). See [Compatibility](compatibility.md) for what `format` promises.

## Folder tree: `report --tree`

```
$ aisignoff report --tree
                       files  Generation      Human review  AI review
.                         30  G0 3% · G3 97%  H1 100%       A1 93% · A2 7%
├─ .github/workflows/      6  G3 100%         H1 100%       A1 100%
├─ docs/                   9  G3 100%         H1 100%       A1 100%
├─ src/aisignoff/          8  G3 100%         H1 100%       A1 88% · A2 12%
└─ tests/                  1  G3 100%         H1 100%       A1 100%
```

The level mix of each folder. Folders that hold nothing but one subfolder share a row; files without a valid declaration are always listed under their folder, with the reason.

| Option | Effect |
|---|---|
| `--depth N` | folders down to depth `N` only (`0`: just the total) |
| `--weight lines` | shares by lines instead of files |
| `--files` | every file, not only the ones with problems |
| `--markdown` | a Markdown table, for the job summary of a CI run |
| `--json` | the whole tree with the counts of each folder |

## The interactive report

```bash
aisignoff report --html aisignoff-report.html --with-source
```

writes a single HTML file, like a coverage report for AI use. It needs no server or internet connection, so it can be opened locally, attached to a release or downloaded from a CI run.

![The folder report of a repository: a sunburst of the folders on the left, the folder table on the right](assets/folder-report.png)

| Option | Effect |
|---|---|
| `--title TITLE` | the page title (default: the repository or folder name) |
| `--with-source` | embeds the text of each file (up to 512 KB each, not binary files) for the line view |
| `--since BASE` | marks what changed since `BASE` (its merge base with `HEAD`), such as `origin/main` in a pull request or the last release tag |

`--with-source` puts the code into the report: share it only with people who may read the repository. Symlinks are never followed.

What it shows:

- **Sunburst.** Each ring is a folder level, each arc as large as its files or lines. Click a folder to zoom in, the centre to go back up.
- **Folder table.** The folders and files of the current folder, with a bar per axis. Sort by a column, for example *Human review* to find the least-reviewed folder.
- **File details.** A file's levels, the names behind them, where they come from and any problems. On GitHub Actions, file names link to the file at that commit.
- **Lines.** A strip of the whole file coloured by each line's level, and with `--with-source` the text itself with the level in the margin. Hover the margin for where a declaration comes from.
- **Changes.** With `--since`, a *Changed* column, a switch to show only what changed, and the changed lines marked `+` in the file details.
- **Find and links.** Type part of a path to jump to it. The address keeps the view, so a link opens the same folder, file and line.

The axis buttons choose what is coloured: **Generation**, **Human review**, **AI review**, or the **Review gap**, a line's generation level minus its human review level, never below 0 (G3 tested at H1 has a gap of 2). Each axis has its own ramp from light (level 0) to dark (level 3), the same in light and dark mode. A folder, which mixes levels, is coloured by:

| Colour | A folder shows |
|---|---|
| **Average** (default) | the weighted average of its levels, between the steps, with a red outline when anything inside is undeclared |
| **Majority** | the level that covers most of its files or lines |
| **Weakest link** | its least-reviewed file, or for generation and the gap the highest |

Excluded files never appear. Undeclared files are red and don't count towards an average.

### Publishing it

| Where | How |
|---|---|
| CI run | `signoff-lint.yml` and `signoff-badges.yml` upload it as an artifact, and write `report --tree --markdown` to the job summary |
| Release | `signoff-release.yml` attaches it to each release |
| GitHub Pages | `signoff-pages.yml` publishes it on every push to `main` |
| A documentation site | write it into the built site, such as `aisignoff report --html site/signoff/index.html` after the build |

This documentation does the last: [the folder report of aisignoff itself](https://industrial-mathematics-group.github.io/aisignoff/signoff/).

## The lines of a change: `aisignoff diff`

```
$ aisignoff diff origin/main --declare-from description.md
Changes since origin/main (f4d6052): +1 −0 lines in 1 file(s)

      +lines  -lines  Generation (added)  Human review (added)  AI review (added)
src/      +1      -0  G3 +1               H1 +1                 A2 +1

Whole repository, by lines:
  Generation: G0 67.6% → 65.7% (-1.9) · G1 2.9% → 2.9% (-0.1) · G3 29.4% → 31.4% (+2.0)
  Human review: H1 0.0% → 2.9% (+2.9) · H2 100.0% → 97.1% (-2.9)
  AI review: A0 67.6% → 65.7% (-1.9) · A1 32.4% → 31.4% (-0.9) · A2 0.0% → 2.9% (+2.9)
```

Like a coverage diff, `diff` shows only what changed since `BASE`: the levels of the added lines, the removed lines (their levels at the base are in `--json`), the attestations the change adds, and how the repository's shares move. It compares the working tree, so it works before committing, against the merge base of `BASE` and `HEAD`, as GitHub shows a pull request.

Before a pull request is merged, its lines have no landing commit yet. `--declare-from FILE` declares them from its description, as the merge or squash commit will ([details](history.md#lines-that-havent-landed-yet)); the level options (`-g`, `-H`, `-a` and the names) declare them directly, and accept `TODO`. Without either, added lines whose commits say an `AI-Generation` show it, with their reviews undeclared. `signoff-pr-diff.yml` writes this to a pull request's job summary.

| Option | Effect |
|---|---|
| `--depth N` | group by folders down to depth `N` (default 1) |
| `--files` | one row per file |
| `--markdown` / `--json` | a Markdown table / everything, machine-readable |

For the same change in the folder report: `aisignoff report --html report.html --with-source --since origin/main`.

## Badges

`aisignoff badge` writes three [shields.io endpoint](https://shields.io/badges/endpoint-badge) files, one per axis, such as `G0 60% · G2 30% · G3 10%`: `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json`. They turn red and show an undeclared share while anything is missing a valid declaration. `--weight lines` weights files by their lines, `--out DIR` sets the folder (default `badges`).

Publish the files somewhere public, such as a `badges` branch (`signoff-badges.yml` does this), and link them from the README, ideally to the folder report:

```markdown
![AI generation](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<owner>/<repo>/badges/aisignoff-generation.json)
![Human review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<owner>/<repo>/badges/aisignoff-human-review.json)
![AI review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<owner>/<repo>/badges/aisignoff-ai-review.json)
```

raw.githubusercontent.com only serves public repositories.
