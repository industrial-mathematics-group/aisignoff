# Compatibility

From version 1.0.0, aisignoff follows [semantic versioning](https://semver.org). This page lists what that covers, so you know what you can rely on when you pin a version in a workflow or a pre-commit hook.

## What stays the same within 1.x

A minor or patch release (1.1, 1.0.1, …) doesn't break any of these. Breaking one of them needs 2.0.

- **The levels.** The three axes, their names (`AI-Generation`, `Human-Review`, `AI-Review`), the levels G0–G3, H0–H3 and A0–A3 and their meaning, and `TODO`.
- **The names.** `Assisted-by`, `Reviewed-by` and `AI-Reviewed-by`.
- **[`SIGNOFF.toml`](signoff-toml.md)**, format `version = 3`. A file that is valid today stays valid and keeps its meaning. New optional keys or tables may be added.
- **[Inline tags](inline-tags.md)**, including the comment syntaxes they are read from.
- **[Line by line](history.md) declarations**: commit trailers, the pull request template's checkboxes, `[[commits]]` and `[[attestations]]`, and the rules that decide which declaration a line takes. A line keeps its levels when you upgrade, unless a release fixes behaviour that contradicts these docs.
- **[Commands](commands.md)**: the commands, their options and the exit codes (`0` all fine, `1` declarations missing or invalid, `2` usage or configuration error). New commands and options may be added.
- **The `--json` output** of `report` and `diff`. It starts with `"format": 1` (and `"aisignoff"`, the version that wrote it). New keys may appear at any time; a key that is removed, renamed or changes its meaning raises `format`, which only happens in a major release. Readers should check `format` and ignore keys they don't know.
- **The badge files** written by `aisignoff badge`: their names and the [shields.io endpoint](https://shields.io/badges/endpoint-badge) schema.

## What may change in any release

- The wording and layout of human-readable output: `lint` messages, `report` text and Markdown tables, `diff` text. Parse `--json` instead.
- The look and behaviour of the [HTML folder report](report.md), including the colours.
- Warnings. A new warning may appear in a minor release, so `lint --strict`, which fails on warnings, can become stricter. Plain `lint` doesn't fail on a repository it accepted before, unless that repository relied on a bug that let an invalid declaration through.
- The Python modules inside the package. aisignoff is a command-line tool; importing it from Python isn't a supported interface.
- Supported Python versions. A minor release may drop a Python version that has reached its end of life. It currently needs Python 3.11 or later.

## Before 1.0

Versions 0.x changed formats freely. [`aisignoff migrate`](migrating.md) converts declarations from versions 1 and 2 of the level scale, and the [changelog](changelog.md) lists what changed in each release.
