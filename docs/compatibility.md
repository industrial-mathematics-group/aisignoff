# Compatibility

aisignoff is at 0.16.0. While the format still changes, it stays below 1.0: a 0.x release may change what this page lists, with a **Breaking** note in the [changelog](changelog.md), so pin an exact version in a workflow or a pre-commit hook. From 1.0.0 on, it follows [semantic versioning](https://semver.org), and this page lists what that covers.

## What 1.x will keep stable

From 1.0, a minor or patch release (1.1, 1.0.1, …) won't break any of these; breaking one will need 2.0.

- **The levels.** The three axes, their names (`AI-Generation`, `Human-Review`, `AI-Review`), the levels G0–G3, H0–H3 and A0–A3 and their meaning, and `TODO`.
- **The names.** `Assisted-by`, `Reviewed-by` and `AI-Reviewed-by`, and the line `AI-Review-Findings`.
- **[`SIGNOFF.toml`](signoff-toml.md)**, format `version = 4`. A file that is valid today stays valid and keeps its meaning. New optional keys or tables may be added; an older 1.x warns about a top-level or `[history]` key it doesn't know (`lint --strict` fails), instead of refusing the file.
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

## Versions

aisignoff went from 0.14 to release candidates for 1.0 (1.0.0rc1 to 1.0.0rc10) and then back to 0.x with 0.15.0, since the format was still changing almost every release. The order of the releases is 0.14, 1.0.0rc1 to 1.0.0rc10, 0.15.0: 0.15.0 has everything the release candidates have. The release candidates are yanked on PyPI, so `pip install aisignoff` and `pip install --pre aisignoff` choose 0.15.0 or later, and an exact pin such as `aisignoff==1.0.0rc10` still installs. These docs name the release candidate that brought a change, as the changelog does; "1.0.0rc6 or later" includes 0.15.0. To change over, pin `0.15.0` where you pinned a release candidate: a version range such as `>=1.0.0rc6` doesn't include it.

## Older versions

1.0.0rc6 changed the AI review scale (`SIGNOFF.toml` version 4, snapshot rules 2); files of version 3 and snapshots of earlier rules are still read, taken over to it ([Upgrading](migrating.md#to-signofftoml-version-4-the-ai-review-scale-of-100rc6)). Versions before 0.12 changed formats freely. Declarations from versions 1 and 2 of the level scale, and `AIDECL.toml`, are no longer read; convert them once with 1.0.0rc1 ([Upgrading](migrating.md#from-aidecl-or-format-version-1-or-2)). The [changelog](changelog.md) lists what changed in each release.
