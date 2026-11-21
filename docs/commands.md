# Command reference

```
aisignoff [--root DIR] COMMAND [OPTIONS]
```

| Command | What it does |
|---|---|
| [`init`](#init) | create `SIGNOFF.toml` |
| [`annotate`](#annotate) | declare files in `SIGNOFF.toml` |
| [`lint`](#lint) | check that everything has a valid declaration |
| [`report`](#report) | summaries, the folder tree and the interactive report |
| [`diff`](#diff) | the levels of the lines changed since a commit |
| [`attest`](#attest) | raise the reviews of whole files, or of the lines of a commit (`[history]`) |
| [`badge`](#badge) | write shields.io badge files |
| [`guide`](#guide) | the brief for an AI agent that writes or reviews a change |

**Global options** go before the command: `--root DIR` runs on another directory (default `.`), `--version` prints the version.

**Exit codes:** `0` success, `1` problems found (`lint`), `2` usage or configuration error.

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
| `--allow-policy-change` | `lint` only, with `--base`: let the change alter `[policy]`, `exclude` or `[history]` of `SIGNOFF.toml`, or remove it. The change itself is still checked under the base branch's `[policy]` |

`lint --declare-from` also checks the description on its own, the base branch's policy applies with `--base`, and a change to its rules fails: see [Checking the pull request description](ci.md#checking-the-pull-request-description).

## init

```bash
aisignoff init [-g G -H H -a A --reviewed-by … [--assisted-by …] [--ai-reviewed-by …]] [--history]
```

Creates a commented `SIGNOFF.toml`. With the three levels, it adds a default annotation for `**`; without them, a commented example. `--history` turns on `[history]` ([Line-level declarations](history.md)); without it, it stays commented out. Refuses if `SIGNOFF.toml` exists, or an `AIDECL.toml` that was never converted.

It also adds a short section to `AGENTS.md` (created if missing, and to `CLAUDE.md` if that exists) that tells AI agents to run [`aisignoff guide`](#guide) before they commit or review. `--no-agents-md` leaves both files alone.

A workflow can set up a repository with defaults that a person completes: `aisignoff init -g TODO -H TODO -a TODO --history` writes a `**` annotation with every level and `Reviewed-by` left `TODO`, which `lint` reports until they are filled in.

## annotate

```bash
aisignoff annotate PATHS -g G -H H -a A [names…] [--precedence closest|override]
```

Appends one annotation for all `PATHS` (files, folders or quoted globs). The levels are required; the declaration must be complete and meet the policy, with `TODO` allowed. See [Declaring files](files.md#annotations-in-signofftoml).

## lint

```bash
aisignoff lint [--strict] [--max-files N] [--declare-from FILE [--author NAME] [--base REV [--allow-policy-change]] | --landed]
```

Fails if any file lacks a valid declaration or falls below the policy, or if no files were found. It also fails on a commit message with an invalid `AI-Review-Findings:` line; a finding of any severity passes ([Findings](levels.md#findings-f0-to-f3)). Problems are grouped, with up to `N` files listed for each (default 10). With `[history]`, it checks every line, and also fails on `[[commits]]` and `[[attestations]]` entries that point nowhere, record files of the review folder without their findings or report (and AI reviews a change adds to `SIGNOFF.toml` without them), `[[commits]]` entries that break the built-in rules or the policy, entries in `.git-blame-ignore-revs` that aren't commits, and a `SIGNOFF.snapshot.json` left from 0.16 or earlier. Lines that haven't landed fail nothing on their own.

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
aisignoff attest PATHS -H H --reviewed-by … [--at REV]                                  # into SIGNOFF.toml
aisignoff attest PATHS -a A --findings SEVERITY --ai-reviewed-by … [--at REV] [--to reviews/FILE.toml | --signoff]
aisignoff attest [PATHS] --commit REV -a A --findings SEVERITY --ai-reviewed-by … [--to reviews/FILE.toml]
```

Writes one `[[attestations]]` entry per file, with the git blob hash of its content; a folder means every declared file below it. Give at least one review level with the names it needs. An AI review of A1, A2 or A3 also gives `--findings` (`none`, `trivial`, `minor`, `major` or `critical`), which sets the [findings level](levels.md#findings-f0-to-f3) of every line of the file. Generation, `--assisted-by` and `TODO` are refused, and so are files under `precedence = "override"`. `--at REV` attests the files as they were at commit `REV`. `--commit REV` attests only the lines that commit of the default branch landed (a pull request's merge or squash commit), in the files given or, without any, in all of them. A person's review (`-H`, also with `-a`) is appended to `SIGNOFF.toml`. An AI review on its own goes into a new record file of the [review folder](history.md#the-review-folder), `reviews/<date>-<commit or file>.toml` (numbered if that exists), or the one `--to FILE` names (directly in the review folder), never into a file that exists; `--signoff` appends it to `SIGNOFF.toml` instead, for a person who records it there. Counts only with `[history]`. See [Raising a review](history.md#raising-a-review-attestations).

## correct

```bash
aisignoff correct REV [-g G] [-H H] [-a A [--findings SEVERITY]] [names…]
```

Appends a `[[commits]]` entry for the commit `REV` to `SIGNOFF.toml` ([Correcting a commit](history.md#correcting-a-commit)): a person's correction of its declaration, axis by axis. `TODO` is refused.

## gc

```bash
aisignoff gc [--dry-run]
```

Deletes the records that cover no line any more: the `[[attestations]]` and `[[commits]]` entries of `SIGNOFF.toml`, and the record files of the review folder all of whose entries cover none. An entry covers no line when its file was deleted, every line of the content it checked has changed since, or its commit owns and wrote no line of a declared file any more. A record of an excluded file, or of a commit that changed one, stays: its lines aren't resolved, and it keeps its levels for when the exclusion is lifted. Deleting them changes no level, and git history keeps them. A record file with one entry that still covers a line stays as it is. `--dry-run` only lists them. Run it on an up-to-date default branch, and land the result in a pull request: the check before the merge lets a change delete a record file of the review folder that covers no line. Needs `[history]` and fails while `lint` reports a problem with the records. Entries of `SIGNOFF.toml` that aren't written as `[[attestations]]` or `[[commits]]` tables (an inline array) can't be told apart by line: `gc` then deletes none and says so. See [Records that cover no line](history.md#records-that-cover-no-line).

## badge

```bash
aisignoff badge [--out DIR] [--weight files|lines] [--landed]
```

Writes `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json` into `DIR` (default `badges`). See [Badges](report.md#badges).

`migrate`, which converted `AIDECL.toml` and the format versions 1 and 2, was removed in 1.0.0rc2; see [Upgrading](migrating.md#from-aidecl-or-format-version-1-or-2).

## guide

```bash
aisignoff guide --role dev       # the agent that writes the change and declares it
aisignoff guide --role review    # the independent AI reviewer
aisignoff guide --agents-md      # point AGENTS.md (and an existing CLAUDE.md) at the two commands
aisignoff guide --skills [DIR]   # write both guides as Claude skills (default DIR: .claude/skills)
```

Prints a one-page brief for an AI agent, so that it doesn't have to read the documentation or the package. The text comes with the installed aisignoff, so it matches the version the repository pins, and ends with what the repository's `SIGNOFF.toml` sets: whether the pull request description or each commit declares the change, the minimum levels, and `exclude`.

- **dev:** which generation level and `Assisted-by` to declare, that human review is left `TODO` for the person, that its own checks are A0, that it never writes `AI-Review-Findings` or records a review for itself, where the declaration goes, and how to check it with `lint`.
- **review:** that the review must be context-free and read-only, how to tell A1, A2 and A3 apart, what to check, the two lists of findings and the [severity scale](levels.md#severity), the lines to give (`AI-Review`, `AI-Reviewed-by`, `AI-Review-Findings`), and how the result becomes F0–F3.

`--agents-md` adds the section between `<!-- aisignoff:begin -->` and `<!-- aisignoff:end -->`, or brings an existing one up to date, and leaves the rest of the file as it is. `--skills` writes `aisignoff-dev/SKILL.md` and `aisignoff-review/SKILL.md`: each tells the agent to run the command and carries the same text as a fallback for where aisignoff isn't installed. Rerun it after an upgrade.
