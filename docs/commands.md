# Command reference

```
aisignoff [--root DIR] COMMAND [OPTIONS]
```

| Command | What it does |
|---|---|
| [`init`](#init) | create `SIGNOFF.toml` |
| [`annotate`](#annotate) | declare files in `SIGNOFF.toml`, or inline |
| [`lint`](#lint) | check that everything has a valid declaration |
| [`report`](#report) | summaries, the folder tree and the interactive report |
| [`diff`](#diff) | the levels of the lines changed since a commit |
| [`attest`](#attest) | raise the reviews of whole files (`[history]`) |
| [`freeze`](#freeze) | record the levels of every line in a snapshot (`[history]`) |
| [`badge`](#badge) | write shields.io badge files |

**Global options** go before the command: `--root DIR` runs on another directory (default `.`), `--version` prints the version.

**Exit codes:** `0` success, `1` problems found (`lint`, `freeze --check`, or a file `annotate --inline` couldn't tag), `2` usage or configuration error.

## Level options

`init`, `annotate`, `attest` and `diff` take a declaration as options:

| Option | Value |
|---|---|
| `-g`, `--generation` | G0–G3 or TODO |
| `-H`, `--human` | H0–H3 or TODO |
| `-a`, `--ai` | A0–A3 or TODO |
| `--assisted-by TOOL` | the AI that wrote it (G1–G3); repeatable |
| `--reviewed-by PERSON` | the responsible human; repeatable |
| `--ai-reviewed-by MODEL` | the AI that reviewed it, and how (A1–A3); repeatable |

`-H TODO` without `--reviewed-by` also writes `Reviewed-by` as `TODO`.

## Options for pull requests and branches

`lint` and `report` take these (`diff` takes the first two, `badge` only `--landed`). They matter only with `[history]`; see [Lines that haven't landed yet](history.md#lines-that-havent-landed-yet).

| Option | Effect |
|---|---|
| `--declare-from FILE` | declare the change that hasn't landed from its pull request description (`-`: standard input), read as its merge or squash commit's message will be. `lint` then requires it to be complete |
| `--author NAME` | with `--declare-from`: who the human review of a ticked template is by |
| `--base REV` | with `--declare-from`: the branch the pull request goes into. If that isn't the default branch, the description declares nothing |
| `--landed` | check `HEAD` as a commit of the default branch: for a merge queue's commit (recognised by itself on GitHub Actions) and release branches. Not with `--declare-from` |

## init

```bash
aisignoff init [-g G -H H -a A --reviewed-by … [--assisted-by …] [--ai-reviewed-by …]]
```

Creates a commented `SIGNOFF.toml`. With the three levels, it adds a default annotation for `**`; without them, a commented example. Refuses if `SIGNOFF.toml` exists, or an `AIDECL.toml` that was never converted.

## annotate

```bash
aisignoff annotate PATHS -g G -H H -a A [names…] [--precedence closest|override] [--inline]
```

Appends one annotation for all `PATHS` (files, folders or quoted globs). The levels are required; the declaration must be complete and meet the policy, with `TODO` allowed. With `--inline`, writes [inline tags](files.md#inline-tags) into each file instead (not with `--precedence`). See [Declaring files](files.md#annotations-in-signofftoml).

## lint

```bash
aisignoff lint [--strict] [--max-files N] [--declare-from FILE [--author NAME] [--base REV] | --landed]
```

Fails if any file lacks a valid declaration or falls below the policy, or if no files were found. Problems are grouped, with up to `N` files listed for each (default 10). With `[history]`, it checks every line, and also fails on `[[commits]]` and `[[attestations]]` entries that point nowhere, entries in `.git-blame-ignore-revs` that aren't commits, and a snapshot that doesn't match its commit. Lines that haven't landed fail nothing on their own.

`--strict` also fails on warnings: annotations that match no file; reverts, `git pull` merges and commits that look like pull requests that own lines without declaring them; review levels in a `[[commits]]` entry for a commit inside a pull request; attestations of files under `precedence = "override"` or with an `AI-Generation`.

## report

```bash
aisignoff report [--files] [--json]
aisignoff report --tree [--depth N] [--weight files|lines] [--files] [--markdown | --json]
aisignoff report --html PATH [--title TITLE] [--with-source] [--since BASE]
```

All forms take the [pull request options](#options-for-pull-requests-and-branches), and `--html` can be combined with `--tree`. See [Reports](report.md).

| Option | Effect |
|---|---|
| `--files` | one line per file (with `--tree`: every file in the tree) |
| `--json` | machine-readable, starting with `format` and `aisignoff` |
| `--tree` | the level mix of each folder |
| `--depth N` | with `--tree`: folders down to depth `N` |
| `--weight files\|lines` | with `--tree`: what the shares count (default `files`) |
| `--markdown` | with `--tree`: a Markdown table |
| `--html PATH` | write the interactive folder report |
| `--title TITLE` | with `--html`: the page title |
| `--with-source` | with `--html`: embed each file's text for the line view |
| `--since BASE` | with `--html`: mark what changed since `BASE` |

## diff

```bash
aisignoff diff BASE [--depth N | --files] [--markdown | --json]
               [--declare-from FILE [--author NAME] | -g G -H H -a A [names…]]
```

The levels of the lines changed between the merge base of `BASE` and `HEAD`, and the working tree. `--declare-from` or the level options (`TODO` allowed) declare the change; they aren't applied to a change that doesn't go into the default branch, or to files under `precedence = "override"`. `--depth N` groups by folders down to depth `N` (default 1), `--files` gives one row per file. See [The lines of a change](report.md#the-lines-of-a-change-aisignoff-diff).

## attest

```bash
aisignoff attest PATHS [-H H] [-a A] [--reviewed-by …] [--ai-reviewed-by …] [--at REV]
```

Appends one `[[attestations]]` entry per file, with the git blob hash of its content; a folder means every declared file below it. Give at least one review level with the names it needs. Generation, `--assisted-by` and `TODO` are refused, and so are files under `precedence = "override"`. `--at REV` attests the files as they were at commit `REV`. Counts only with `[history]`. See [Raising a review](history.md#raising-a-review-attestations).

## freeze

```bash
aisignoff freeze [--prune] [--reset FILE...] [--allow-warnings]
aisignoff freeze --check
```

Writes `SIGNOFF.snapshot.json`, the levels of every line as of the checked-out commit of the default branch. Needs `[history]`, a clean working tree and a `lint` that passes there. See [Snapshots](snapshots.md).

| Option | Effect |
|---|---|
| `--prune` | move the `[[commits]]` and `[[attestations]]` entries of `SIGNOFF.toml` into the snapshot's archive |
| `--reset FILE...` | work these files out from history again instead of keeping their frozen levels |
| `--allow-warnings` | freeze although `lint` has warnings |
| `--check` | only check that the committed snapshot is what `freeze` writes at its commit; not with `--prune` or `--reset` |

## badge

```bash
aisignoff badge [--out DIR] [--weight files|lines] [--landed]
```

Writes `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json` into `DIR` (default `badges`). See [Badges](report.md#badges).

`migrate`, which converted `AIDECL.toml` and the format versions 1 and 2, was removed in 1.0.0rc2; see [Upgrading](migrating.md#from-aidecl-or-format-version-1-or-2).
