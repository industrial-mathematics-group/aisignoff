# Commands

| Command | What it does |
|---|---|
| `aisignoff init` | Create `SIGNOFF.toml`, optionally with a default for all files |
| `aisignoff annotate PATHS …` | Append an annotation, or tag the files themselves with `--inline` |
| `aisignoff attest PATHS …` | Re-declare whole files as reviewed now ([line by line](history.md)) |
| `aisignoff diff BASE` | The levels of the lines changed since `BASE` |
| `aisignoff lint` | Fail if any file lacks a valid declaration |
| `aisignoff report` | Summarise the declarations, per folder with `--tree`, as an interactive page with `--html` |
| `aisignoff badge` | Write shields.io badge files |
| `aisignoff migrate` | Convert declarations of earlier versions |

**Global options,** given before the command:

- `--root DIR` runs on another directory, e.g. `aisignoff --root ../paper lint`.
- `--version` prints the version.

**Exit codes:** `0` success, `1` problems found by `lint`, `2` usage or configuration errors.

## Levels and names

`init` and `annotate` take the same options:

| Option | Value |
|---|---|
| `-g`, `--generation` | G0–G3 or TODO |
| `-H`, `--human` | H0–H3 or TODO |
| `-a`, `--ai` | A0–A3 or TODO |
| `--assisted-by TOOL` | the AI that wrote it (G1–G3); repeatable |
| `--ai-reviewed-by MODEL` | the AI that reviewed it, and how (A1–A3); repeatable |
| `--reviewed-by PERSON` | the responsible human; repeatable |

## init

```bash
aisignoff init [-g G -H H -a A --reviewed-by …]
```

Creates a commented `SIGNOFF.toml`. With the levels, it adds a default annotation for `**`; without them, an example. Refuses if `SIGNOFF.toml` (or the old `AIDECL.toml`) already exists.

## annotate

```bash
aisignoff annotate PATHS -g G -H H -a A [--assisted-by …] [--ai-reviewed-by …] --reviewed-by … [--precedence closest|override] [--inline]
```

Appends one annotation for all `PATHS` (files, folders or quoted globs), or with `--inline` writes [inline tags](inline-tags.md) into each file. See [What annotate checks](getting-started.md#what-annotate-checks).

## attest

```bash
aisignoff attest PATHS [-g G] [-H H] [-a A] [--assisted-by …] [--ai-reviewed-by …] [--reviewed-by …] [--at REV]
```

Appends one `[[attestations]]` entry per file (directories: every declared file below), with the git blob hash of its content. Give at least one level, with the names it needs; TODO isn't allowed. Counts only with `[history]` enabled. See [Re-declaring a whole file](history.md#re-declaring-a-whole-file).

- `--at REV` attests the files as they were at commit `REV`.

## diff

```bash
aisignoff diff BASE [--depth N | --files] [--markdown | --json] [-g G -H H -a A --assisted-by … …]
```

The levels of the lines added since `BASE` (a commit, branch or tag), the removed lines, new attestations and how the repository's shares move. Compares the working tree with the merge base of `BASE` and `HEAD`, as a pull request's diff on GitHub does, so commits `BASE` got since don't count; the state there is read from a temporary git worktree. The level options declare lines after `BASE` that have no declaration of their own. See [Showing a change](history.md#showing-a-change-aisignoff-diff).

## lint

```bash
aisignoff lint [--strict] [--max-files N]
```

Fails if any file lacks a valid declaration, falls below the policy, or if no files were found. Problems are grouped, with up to `N` files listed each (default 10). With [`[history]`](history.md), it checks every line, and also fails on `[[commits]]` and `[[attestations]]` entries that point nowhere.

- `--strict` also fails on annotations that match no file.

## report

```bash
aisignoff report [--files] [--json]
aisignoff report --tree [--depth N] [--weight files|lines] [--files] [--markdown | --json]
aisignoff report --html PATH [--title TITLE] [--with-source] [--since BASE]
```

A summary per axis by default (with `[history]`: by lines). Invalid declarations count as "undeclared", as in the badges.

- `--files`: one line per file, with its levels, where they come from, and any problems.
- `--json`: the same per file, machine-readable.
- `--tree`: the level mix of each folder. With `--markdown` a Markdown table (for job summaries), with `--json` the whole tree with its counts.
- `--html PATH`: an interactive folder report in a single HTML file. `--with-source` embeds the text of each file for its line view, `--since BASE` marks what changed since `BASE` (since its merge base with `HEAD`, as `diff`).

Both are described in [Folder report](report.md).

## badge

```bash
aisignoff badge [--out DIR] [--weight files|lines]
```

Writes shields.io endpoint files `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json` into `DIR` (default `badges`). See [CI and badges](ci.md#badges).

- `--weight lines` weights each file by its number of lines instead of counting files.

## migrate

```bash
aisignoff migrate [--dry-run] [--from 2]
```

Renames `AIDECL.toml` to `SIGNOFF.toml` and converts declarations of earlier format versions, all or nothing. See [Migrating](migrating.md).

- `--dry-run` only shows what would change.
- `--from 2` treats inline tags as version 2 in a repository without `SIGNOFF.toml`.
