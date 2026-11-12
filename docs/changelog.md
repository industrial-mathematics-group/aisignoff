# Changelog

What changed in each release. From 1.0.0 on, aisignoff follows semantic versioning as described in [Compatibility](compatibility.md).

## 1.0.0

The first stable release. Formats, command-line options and the `--json` output now only change in a compatible way within 1.x.

- **Breaking:** the `--json` output of `report` and `diff` starts with `"format": 1` and `"aisignoff"` (the version that wrote it). `report --json` is now an object with the files under `"files"`, instead of a bare list. Change `json.load(f)` to `json.load(f)["files"]`; the [example workflow](integration.md) does this already.
- New [Compatibility](compatibility.md) page: what 1.x promises and what may still change.
- This changelog.

## 0.11.0

- [Folder report](report.md): each axis has its own colour ramp, whose hue shifts as it darkens, the same in light and dark mode.
- The review gap is a fourth axis in the sunburst, the line view and the table.
- The new *Average* folder colour is the default: a folder is coloured between the steps by its weighted average level.
- Fixes from the review of 0.10.1.

## 0.10.1

- Fixes from the review of 0.10.0, among them A1 on human-written lines, Markdown that hid a declaration, `diff --declare` on the branch itself, `git log` read NUL-separated, the rebase merge preview and `push` events.
- A review raised by a commit inside a pull request is kept, and `lint` warns about it (`--strict` fails).

## 0.10.0

- Declarations per axis: generation comes from the most specific declaration (attestation, branch commit, inner merge, landing commit), reviews take the highest.
- A commit that declares some axes but leaves one out is an error.
- New settings `merge-method` and `ignore-whitespace` in [`[history]`](history.md).

## 0.9.0

- A merge commit declares the lines of its branch; the branch's own commits override it per axis.
- A commit uses either trailers or checkboxes, not both.

## 0.8.0

- [Line by line](history.md) declarations read the ticked boxes of the pull request template in squash commits, so `SIGNOFF.toml` no longer needs an annotation per pull request.

## 0.7.1

- Fixes from the review of 0.7.0.

## 0.7.0

- Line view in the HTML report: `--with-source` embeds the files, `--since BASE` marks what changed.

## 0.6.0

- [Line by line](history.md) declarations from git history: `[history]`, commit trailers, `[[commits]]` and `[[attestations]]`.
- New commands `attest` and `diff`.

## 0.5.0

- [Folder report](report.md): `report --tree` and `report --html`.
- [Example workflows](integration.md) and a pre-commit hook.
- Documentation built with Zensical.

## 0.4.x

- Renamed from `aidecl` to aisignoff, with `SIGNOFF.toml` instead of `AIDECL.toml`, and published on PyPI. `aisignoff migrate` renames the old file and converts declarations from versions 1 and 2 of the level scale.
- Documentation site on GitHub Pages.
