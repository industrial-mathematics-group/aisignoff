# Compatibility

aisignoff is at its second release candidate for 1.0 (1.0.0rc2). From 1.0.0 on, it follows [semantic versioning](https://semver.org), and this page lists what that covers, so you know what to rely on when you pin a version in a workflow or a pre-commit hook. A release candidate may still change these formats before 1.0.0, with a note in the [changelog](changelog.md).

## What 1.x will keep stable

From 1.0, a minor or patch release (1.1, 1.0.1, …) won't break any of these; breaking one will need 2.0.

- **The levels.** The three axes, their names (`AI-Generation`, `Human-Review`, `AI-Review`), the levels G0–G3, H0–H3 and A0–A3 and their meaning, and `TODO`.
- **The names.** `Assisted-by`, `Reviewed-by` and `AI-Reviewed-by`.
- **[`SIGNOFF.toml`](signoff-toml.md)**, format `version = 3`. A file that is valid today stays valid and keeps its meaning. New optional keys or tables may be added; an older 1.x warns about a top-level or `[history]` key it doesn't know (`lint --strict` fails), instead of refusing the file.
- **[Inline tags](files.md#inline-tags)**, including the comment syntaxes they are read from.
- **[Line-level](history.md) declarations**: commit trailers, the pull request template's checkboxes, `[[commits]]` and `[[attestations]]`, and the rules that decide which declaration a line takes. A line keeps its levels when you upgrade, unless a release fixes behaviour that contradicts these docs. With a [snapshot](snapshots.md), the lines in it keep their levels in any case.
- **`SIGNOFF.snapshot.json`**, format `"format": 1`: a snapshot that is valid today stays valid and keeps its meaning. It records the `"rules"` it was written under. A release that changes the levels some line gets, such as a fix, raises that number. A snapshot on the default branch stays accepted as it is whatever its rules; a changed one is checked only when it was written under the running version's rules, so write a new snapshot with the version your CI uses.
- **[Commands](commands.md)**: the commands, their options and the exit codes (`0` all fine, `1` declarations missing or invalid, `2` usage or configuration error). New commands and options may be added.
- **The `--json` output** of `report` and `diff`, with [the keys listed here](report.md#json-output). It starts with `"format": 1` (and `"aisignoff"`, the version that wrote it). New keys may appear at any time; a key that is removed, renamed or changes its meaning raises `format`, which (from 1.0) only happens in a major release. Readers should check `format` and ignore keys they don't know.
- **The badge files** written by `aisignoff badge`: their names and the [shields.io endpoint](https://shields.io/badges/endpoint-badge) schema.

## What may change in any release

- The wording and layout of human-readable output: `lint` messages, `report` text and Markdown tables, `diff` text. Parse `--json` instead.
- The look and behaviour of the [HTML folder report](report.md#the-interactive-report), including the colours.
- Warnings. A new warning may appear in a minor release, so `lint --strict`, which fails on warnings, can become stricter. Plain `lint` doesn't fail on a repository it accepted before, unless that repository relied on a bug that let an invalid declaration through.
- The Python modules inside the package. aisignoff is a command-line tool; importing it from Python isn't a supported interface.
- Supported Python versions. A minor release may drop a Python version that has reached its end of life. It currently needs Python 3.11 or later.

## Older versions

Versions before 0.12 changed formats freely. Declarations from versions 1 and 2 of the level scale, and `AIDECL.toml`, are no longer read; convert them once with 1.0.0rc1 ([Upgrading](migrating.md#from-aidecl-or-format-version-1-or-2)). The [changelog](changelog.md) lists what changed in each release.
