# The 1.0 contract

!!! warning "Draft"
    This is the draft of what aisignoff 1.0.0 will promise. It is not in force yet: aisignoff is at 0.20.1, and 0.x releases may still break any of it ([Compatibility](compatibility.md)). The items marked **Before 1.0** were not true of 0.20.1 and must be done, or taken out of this page, before 1.0.0 is released; those marked *(#68)* are done in the pull request for 0.21.0. The decisions, taken and still open, are listed [at the end](#decisions).

This page says exactly what every 1.x release keeps: what a repository, a workflow or a script can rely on when it raises its pin from 1.x to a later 1.y. [Compatibility](compatibility.md) is the short version for readers; where the two differ, this page counts.

The words **must**, **must not**, **may** and **will** are used as in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119): "aisignoff will" is a promise of every 1.x release, "a repository must" is a condition for that promise.

## 1. Versions

1. **Semantic versioning.** From 1.0.0, aisignoff follows [semantic versioning 2.0.0](https://semver.org). A minor release (1.1.0) may add, a patch release (1.0.1) only fixes. Anything this page calls stable changes only in a major release (2.0.0).
2. **A breaking change** is any change that makes a repository, a workflow or a script that followed this page fail, pass or report differently, except the changes listed under [Not covered](#10-not-covered) and [fixes](#3-fixes-that-change-levels).
3. **Deprecation.** Before 2.0 removes or changes something stable, a 1.x release must deprecate it: the docs and the changelog say so, and where aisignoff can see the use, it warns. A deprecated feature keeps working until 2.0.
4. **The changelog** (`docs/changelog.md`) names every change in one of these sections: **Breaking** (major releases only), **Levels** (a fix that changes the levels of existing lines, see below), **Deprecated**, **Added**, **Fixed**, **Changed** (for what this page doesn't cover).
5. **Pins.** A workflow pins an exact version (`aisignoff==1.2.3`), and raises it on purpose. aisignoff never changes a result because a newer release exists.
6. **Release candidates.** No release candidate of 1.0.0 will be published (the yanked `1.0.0rc1` to `1.0.0rc10` stay yanked); 1.0.0 follows the last 0.x release directly.

## 2. What a result depends on

A result is the levels, names and findings of each file and line, the problems `lint` reports, and the `--json` and badge output.

1. **Inputs.** A result depends only on:
    - the files of the working tree that git doesn't ignore, and their content;
    - `SIGNOFF.toml` and the record files of the review folder;
    - the commits, trees and blobs of the repository, and which commit the default branch is at ([`default-branch`](signoff-toml.md#history));
    - the options of the command, and the environment variables of [section 8](#8-environment);
    - the description given with `--declare-from`.
2. **Not inputs.** It doesn't depend on the user's or the system's git configuration, on `git replace` refs, on `.gitattributes` diff drivers, text conversion or filters, on the blame cache, on the time, the locale, the number of processors, or the order in which the file system lists files. **Before 1.0** *(#68)*: aisignoff pins `diff.indentHeuristic`, runs `git blame` with `--no-textconv`, and sets `GIT_NO_REPLACE_OBJECTS=1`. In 0.20.1 each of the three can change the levels of lines.
3. **git.** aisignoff needs git 2.34 or later (Ubuntu 22.04's). It reads history only through git ([D5](#decisions)). **Before 1.0** *(#68)*: it checks the version at start and stops with exit code `2` below it; 0.20.1 silently reads some history wrong on git 2.23–2.30.
4. **Same input, same result.** Two runs with the same inputs and the same git version give the same result, whatever the machine. The cache changes only how long a run takes.
5. **git versions.** git's line diff can change between git releases, and then so can the owner of a line next to an edit. A change of git version is not a change of aisignoff; pin git in CI if that matters to you (a container image does). **Before 1.0** *(#68)*: the cache key includes the git version, so a CI cache written by another git isn't mixed in.

## 3. Fixes that change levels

aisignoff works out every line from the whole history on each run. A fix of how a line is resolved therefore changes the levels of existing lines when you upgrade. That is allowed in a minor or patch release only when:

1. the behaviour before contradicted this page or a page it names as normative ([section 5](#5-how-a-line-is-resolved)); a behaviour that this page and those pages don't decide is not "a bug" but a gap, which a 1.x release must decide in the way that changes no existing line, and document;
2. the changelog lists the fix under **Levels**, with what changes and for which lines;
3. the fix changes no line that the documented rules already decided correctly.

## 4. Declarations

### 4.1 Levels and names

The vocabulary is fixed for 1.x. Its meanings are those of [Levels and rules](levels.md) as of 1.0.0, which in turn follow the [AI policy](https://github.com/industrial-mathematics-group/.github/blob/main/.github/CONTRIBUTING.md#ai-assisted-contributions) of the Industrial Mathematics Group. A change of that policy that changes what a level means needs aisignoff 2.0 and a new `SIGNOFF.toml` version; one that only rewords it doesn't.

| What | Stable values |
|---|---|
| Axes and their keys | `AI-Generation`, `Human-Review`, `AI-Review` |
| Levels | `G0`–`G3`, `H0`–`H3`, `A0`–`A3` (upper case), and `TODO` |
| Names keys | `Assisted-by`, `Reviewed-by`, `AI-Reviewed-by` |
| Findings key and values | `AI-Review-Findings`: `none`, `trivial`, `minor`, `major`, `critical` |
| Findings levels (shown, never declared) | `F-`, `F0`–`F3` |

These rules of [What a valid declaration needs](levels.md#what-a-valid-declaration-needs) are stable: which names each level needs or forbids, "a self-check is A0", "A2 and A3 need a different model", with model names compared by their words without the vendor in brackets and without version numbers, and that the review levels and the policy minimums are cumulative. The [model tiers](levels.md#model-tiers) are guidance and not checked; they are not part of this contract.

### 4.2 `SIGNOFF.toml`

1. **Format.** 1.x reads and writes `version = 4`, as the [SIGNOFF.toml reference](signoff-toml.md) of 1.0.0 describes it. It still reads `version = 3` as described there. A file valid under 1.0 stays valid under every 1.x and means the same.
2. **A newer file.** `version = 5` or higher is a configuration error (exit code `2`) that says the file needs a newer aisignoff. A new version of the format comes only with 2.0. **Before 1.0** *(#68)*: 0.20.1 says "'version = 4' is required" instead.
3. **Keys.** The keys of 1.0 are the keys of 1.x: they are integral to a declaration, so they don't change. *Proposed, [D2](#decisions):* they are **core keys**, which an aisignoff must understand: a key it doesn't know is a configuration error (exit code `2`) that says it is a typo or a key of a newer aisignoff, wherever it is (today the top level, `[history]` and `[review]` only warn). A 1.x release may add a core key only as something a repository opts into, which then pins that release. Keys that start with `X-` are **optional keys**, for a team's or a tool's own information: allowed in every table, never read, never an error, and never a change of any result.
4. **Defaults.** The default of an existing key doesn't change in 1.x.
5. **What aisignoff writes** (`init`, `annotate`, `attest`, `correct`, `gc`): the entries it writes and deletes mean what the commands' reference says. The layout, order and comments of the text it writes are not covered. `gc` deletes only entries that cover no line, and leaves the file as it is when it can't tell the entries apart.

### 4.3 Commit messages and pull request descriptions

A commit message, or a pull request description read as the message of its merge or squash commit, declares with **key lines** or with the **boxes of a template**. The grammar below is normative. A message that doesn't use it declares nothing. A 1.x release may add warnings for text that looks like a declaration but isn't one (as there is one today for `AI-Review-Finding:`); it may not start reading such text as a declaration.

**Text that doesn't count.** The subject line, and lines inside fenced code blocks (```` ``` ```` or `~~~`) and HTML comments (`<!-- … -->`). A fence or comment that is never closed doesn't open one.

**Key lines.**

- A key line starts at the beginning of a line, with no whitespace, bullet or emphasis before the key, and has the form `Key: value`, with no space before the colon. It may be anywhere in the body, not only in git's trailer block.
- Keys are matched without regard to case. Level values are matched exactly: `G3` and `TODO` are levels, `g3` or `todo` is an invalid level, which is an error.
- An empty level (`Human-Review:`) is `TODO`.
- Names keys may be repeated, and each line is one name, commas included. Repeated names count once.
- The same level key given twice with the same value counts once; with different values it is an error.
- An axis counts when its level is given: a names line on its own declares nothing.
- Lines with other keys are ignored.
- The **findings line** is also read in a looser form: after a bullet, emphasis or whitespace, in any case. With several findings lines, the most severe counts. A value that isn't one of the five is an error.

**Template boxes** (the [pull request template](history.md#pull-request-descriptions) of the Industrial Mathematics Group is one; the grammar doesn't depend on its wording):

- A box is a line that starts, after optional indentation, with `-` or `*`, whitespace, `[ ]`, `[x]` or `[X]`, and whitespace. Other list markers (`+`, numbers) aren't boxes.
- A **level box** has the level in bold as the first thing after the box: `**G2**`, `**H1**`, `**A0**`.
- **Generation:** exactly one ticked G box; two are an error. G boxes that are there with none ticked are `TODO`.
- **Assisted-by:** the ticked boxes between the last G box and the first H box whose bold text has no colon, written `**Name** (Vendor)`, and the text after a ticked `**Other:**`.
- **Human review:** the highest ticked H box. H boxes with none ticked are `TODO`. A ticked box above an unticked one is an error. The name is the commit's author, or before the merge `lint --author`, or the login of a line `Responsible person: @login` in a pull request opened by an account whose login ends in `[bot]`.
- **AI review:** the highest ticked A box, or `A0` when A boxes are there and none is ticked. `AI-Reviewed-by` is the text after `Model` and the next colon in that box (`Model:`, `Model and report:`). An A1 box without that text names the models of `Assisted-by`, as a new session. A ticked A1 box whose text says "its own work" or "self-check" is the template of `version = 3` and an error under `version = 4`.
- Key lines and ticked level boxes in one message are an error until a `[[commits]]` entry settles it.

**Before 1.0** *(#68)*: this grammar is written into [Declaring lines](history.md) (section "The exact form" in #68), which then counts as normative for it; in 0.20.1 parts of it are only in the code.

### 4.4 The review folder

1. The review folder is `reviews/`, or `[review] dir`. Its files need no declaration.
2. **Record files** are the `.toml` files directly in it, holding `[[attestations]]` tables with `path`, `blob` or `commit`, `AI-Review` (`A1`–`A3`), `AI-Reviewed-by` and `AI-Review-Findings`, and nothing else ([4.2.3](#42-signofftoml) applies to new keys). Files in its subfolders are never read.
3. **Add-only.** The check before the merge fails a change that modifies, deletes or renames a file in it, except deleting a record file that covers no line.
4. The name `attest` gives a new record file, `reviews/<date>-<commit or file>.toml`, is not covered: name it with `--to` if you rely on it.

## 5. How a line is resolved

The rules that turn history into the levels of a line are stable. They are those of [Declaring lines](history.md), [Findings](levels.md#findings-f0-to-f3) and [Who writes what](signoff-toml.md#who-writes-what) as of 1.0.0, which are normative for this, in short:

1. **One owner.** The owner of a line is the commit that `git blame --first-parent` gives it on the default branch, with `-w` when `ignore-whitespace` is on and skipping the commits of the ignore-revs file. The owner's message declares the line; a `[[commits]]` entry for the owner replaces the axes it gives.
2. **Generation inside a merge.** A commit inside a merge that wrote a line may raise, never lower, its `AI-Generation`; a `[[commits]]` entry for that commit may lower it.
3. **Reviews.** Each review level is the higher of the owner's and that of an attestation whose checked content had the line; the names of the attestation on a tie. `TODO` is below every level.
4. **Nothing declared.** An owner that declares nothing leaves its lines to the file-level declaration, or fails `lint` under `undeclared = "error"` or after `require-trailers-since`. An owner that declares some axes but not all is an error, unless an attestation gives the missing review.
5. **Findings.** The newest AI review of A1–A3 that gave findings and covers a line sets its findings level. Reviews are ordered by the commit of the default branch that recorded them, and where two saw different content of the file, the review of the newer content counts. A line that a later commit changes is `F-` until a review covers it.
6. **Units.** A binary file (a NUL byte in the first 16,384 bytes of its content as git stores it), an empty file and a symlink are one unit, counted as one line, owned by the commit that last changed it. What a text file takes from an earlier binary version of it is open ([D6](#decisions)).
7. **Lines that haven't landed** are the diff against the newest commit of the default branch that `HEAD` contains, and fail nothing on their own.

**Before 1.0:**

- *(#68)* These rules existed only in the code and become part of [Declaring lines](history.md): the binary probe; that binary units follow exact renames only; how reviews recorded in one commit are ordered (`SIGNOFF.toml`, then record files by path, then by position); how the age of a `SIGNOFF.toml` entry is found; what a line at a shallow boundary or from an unknown commit takes; when a generation raised inside a merge is dropped.
- Rule 6 is inconsistent in 0.20.1: before a change lands, every line of a text file that replaces a binary one is the change's; after it lands, `git blame` gives the lines it finds in the binary version to the commit that added that version. One of the two must change before 1.0 ([D6](#decisions)).

## 6. Commands

### 6.1 Commands and options

The commands `init`, `annotate`, `lint`, `report`, `diff`, `attest`, `correct`, `gc`, `badge` and `guide`, the global options `--root` and `--version`, and every option of the [command reference](commands.md) of 1.0.0 are stable: their names, what they take, and what they do as the reference describes it. New commands and options may be added. An option's default doesn't change in 1.x.

### 6.2 Exit codes

| Code | Meaning | Who returns it |
|---|---|---|
| `0` | The command did what was asked. For `lint`: everything is declared and valid | every command |
| `1` | `lint` found a problem: a declaration missing, invalid or below the policy, a record that points nowhere, a problem the check before the merge reports, no files found, or with `--strict` a warning | `lint` only |
| `2` | The command couldn't run: a usage error, an invalid or unreadable `SIGNOFF.toml` or record file, a setting that names something that doesn't exist (`default-branch`, `ignore-revs-file`, `require-trailers-since`), a file that can't be read or written, a git that is missing, too old or fails; with a message and no traceback | every command |
| `3` | An internal error: a bug in aisignoff, with the traceback and where to report it ([D3](#decisions)) | every command |

`report`, `diff` and `badge` return `0` when they ran, whatever the declarations are; read `errors` in `--json`.

**Before 1.0** *(#68)*: in 0.20.1 an unexpected error (a `SIGNOFF.toml` that isn't UTF-8, a file that can't be written, `badge --out` naming a file) prints a traceback and exits with `1`, so a workflow can't tell it from a failed check; and a setting that names nothing makes `lint` exit with `1` and `report` and `badge` exit with `0` with wrong data.

### 6.3 `--json` output, format 1

`report --json`, `report --tree --json` and `diff --json` write an object that starts with `"format": 1` and `"aisignoff"` (the version that wrote it). Format 1 is the keys listed under [JSON output](report.md#json-output) in 1.0.0, with the meaning given there.

- New keys may appear in any 1.x release. A reader must ignore keys it doesn't know and should check `format`.
- Removing or renaming a key, or changing its meaning, type or scale, raises `format`, and happens only in 2.0.
- The text of `source`, of messages (`errors`, `problems`, `notes`, `note`), and of names that aisignoff writes itself (such as the A1 reviewer of a template without a model) is not covered.

**Before 1.0** *(#68)*: the list under JSON output is made to match what 0.20.1 writes: `runs` is a list of `[first, last]` pairs; `counts.*.files` in the tree is a number of files (fractions where a file has lines of several levels), not a share; `before` and `after` of `diff` are percentages (0 to 100); `attested` entries have `commit`, and `path` may be `null`; they have `findings` for A1 too.

### 6.4 Badges

`badge` writes `aisignoff-generation.json`, `aisignoff-human-review.json`, `aisignoff-ai-review.json` and `aisignoff-findings.json`, UTF-8, in the [shields.io endpoint](https://shields.io/badges/endpoint-badge) schema (`schemaVersion` 1, `label`, `message`, `color`). The file names and the schema are stable; the text of `label` and `message` and the colours are not. **Before 1.0** *(#68)*: the command reference lists the fourth file, and the files are written as UTF-8 whatever the locale.

### 6.5 `guide`

The roles `dev` and `review`, the markers `<!-- aisignoff:begin -->` and `<!-- aisignoff:end -->` that `init` and `guide --agents-md` write, and the skill folders `aisignoff-dev` and `aisignoff-review` are stable. The text of the guides is not: it follows the rules of the release.

### 6.6 pre-commit

The hook id `aisignoff-lint` in `.pre-commit-hooks.yaml` is stable.

## 7. The blame cache

The cache lives in `.git/aisignoff/`, the path a CI workflow restores and saves; that path is stable. Its files and their format are not: a release may stop using a cache an older one wrote, which costs one slower run. `AISIGNOFF_NO_CACHE=1` turns it off. A result never depends on the cache ([2.4](#2-what-a-result-depends-on)).

## 8. Environment

| Variable | Effect | Stable |
|---|---|---|
| `GITHUB_REF` | a ref under `refs/heads/gh-readonly-queue/` makes `lint` check `HEAD` as landed, as `--landed` | yes |
| `GITHUB_EVENT_PATH` | the event's default branch, when `origin` names none | yes |
| `AISIGNOFF_NO_CACHE` | `1` turns the cache off | yes |
| `GITHUB_SHA`, `GITHUB_REPOSITORY`, `GITHUB_SERVER_URL` | links in the HTML report | no (the report isn't covered) |

**Platforms.** aisignoff 1.x supports Linux ([D4](#decisions)): its main use is in containers, such as GitHub Actions' runners. It supports the CPython versions that are not past their end of life when the release is made, from 3.11 on. A minor release may drop a Python version past its end of life. Other systems may work, but aren't tested. **Before 1.0:** CI tests every supported Python version, including 3.14, and the lowest supported git. The workflow change is in the description of #68: the GitHub App that opens pull requests can't push workflow files.

## 9. What a repository must do

The promises above hold for a repository that:

- keeps the whole history of the default branch in CI (`fetch-depth: 0`);
- lets merge and squash commits carry the pull request description, when it declares with descriptions;
- doesn't rewrite the history of the default branch;
- pins the aisignoff version in every workflow and in the pre-commit hook, and raises them together.

## 10. Not covered

These may change in any release, with an entry under **Changed**:

- the wording and layout of human-readable output: `lint` messages, `report` text and Markdown tables, `diff` text;
- the HTML folder report, its look, its colours and its syntax highlighting;
- new warnings: `lint --strict` may become stricter in a minor release. Plain `lint` doesn't fail on a repository it accepted before, unless that repository relied on a bug that let an invalid declaration through, and such a fix is listed under **Fixed**;
- the Python modules of the package: importing aisignoff isn't supported;
- the example workflows and scripts in `examples/`, and the organisation's reusable workflows, which pin their own version;
- the layout of the TOML that commands write, and the names of record files that `attest` chooses;
- the guides' text and the model tiers.

## Decisions

Taken on 25 November 2026:

- **D1. When:** not yet. 1.0.0 waits; this page stays a draft until the maintainers set a date.
- **D3. Exit codes:** a separate code `3` for internal errors, so that a bug in aisignoff can be told from a configuration error (`2`) and from a failed check (`1`).
- **D4. Platforms:** Linux only. The main use is in containers, such as GitHub Actions.
- **D5. git:** aisignoff keeps reading history through git, which is more robust and efficient than its own line diff would be. A change of git version is outside the promise of [3](#3-fixes-that-change-levels).

Open:

- **D2. Keys.** The keys stay the same in 1.x. Proposed, as in [4.2.3](#42-signofftoml): the keys of today are core keys that every aisignoff must understand (unknown ones are errors everywhere, also at the top level and in `[history]` and `[review]`, where they only warn today), and keys starting with `X-` are optional keys that aisignoff never reads. Alternative: keep today's mix.
- **D6. A text file after a binary one.** Before a change lands, aisignoff counts every line of a text file that replaces a binary one as the change's; once it has landed, `git blame` matches lines through the binary version and gives them to the commit that added it. Proposed: follow git (`git blame` decides the owner of every line of a text file; being binary only makes the current version one unit), and make the check before the merge show the same, which removes code instead of adding it. Alternative: keep "a text side that replaces a binary one is all new" and enforce it in landed history too, which means reading every version of every file once (cached), in the area with the most findings so far.
