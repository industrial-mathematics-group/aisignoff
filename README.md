# aisignoff

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24020702.svg)](https://doi.org/10.5281/zenodo.24020702)
[![PyPI](https://img.shields.io/pypi/v/aisignoff.svg)](https://pypi.org/project/aisignoff/)
[![Docs](https://img.shields.io/badge/docs-online-9558B2.svg)](https://industrial-mathematics-group.github.io/aisignoff/)

[![AI generation](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/badges/aisignoff-generation.json)](https://industrial-mathematics-group.github.io/aisignoff/signoff/)
[![Human review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/badges/aisignoff-human-review.json)](https://industrial-mathematics-group.github.io/aisignoff/signoff/)
[![AI review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/badges/aisignoff-ai-review.json)](https://industrial-mathematics-group.github.io/aisignoff/signoff/)

**Declare and check how each file in a repository was created and reviewed:** how much an AI generated (G0–G3), how thoroughly a human reviewed it (H0–H3), and how thoroughly an AI reviewed it (A0–A3).

It works like [REUSE](https://reuse.software) does for licences: a path-based `SIGNOFF.toml`, optional tags in file headers, and a `lint` command for CI. The name is meant both ways: the AI signs off, and so does the human ("ai", said in German, sounds like "I"). It's a declaration, not a cryptographic signature.

## Install

```bash
pipx install aisignoff        # or: uv tool install aisignoff, or: pip install aisignoff
```

Requires Python 3.11 or newer; no other dependencies.

## Quick start

```bash
# a default for everything: written by a human, reviewed line by line, no AI review
aisignoff init -g G0 -H H2 -a A0 --reviewed-by "Jane Doe"

# what is different, by file, folder or glob
aisignoff annotate results/ -g G2 -H H1 -a A1 \
    --assisted-by "Claude Opus 5.5 (Anthropic)" \
    --ai-reviewed-by "Claude Opus 5.5 (Anthropic), same session" --reviewed-by "Jane Doe"

# every file declared correctly?
aisignoff lint
```

This writes a `SIGNOFF.toml` like this (`init` also adds explanatory comments):

```toml
version = 3

[[annotations]]
path = "**"
AI-Generation = "G0"
Human-Review = "H2"
AI-Review = "A0"
Reviewed-by = ["Jane Doe"]

[[annotations]]
path = "results/**"
AI-Generation = "G2"
Human-Review = "H1"
AI-Review = "A1"
Assisted-by = ["Claude Opus 5.5 (Anthropic)"]
Reviewed-by = ["Jane Doe"]
AI-Reviewed-by = ["Claude Opus 5.5 (Anthropic), same session"]
```

## Line by line

With `[history]` in `SIGNOFF.toml`, aisignoff declares each line by the commit that landed it on the default branch (trailers like `AI-Generation: G2`, or the ticked boxes of the pull request template, in the merge or squash commit of a pull request), keeps the file-level declarations as the fallback, and `aisignoff attest` re-declares a whole file after a review. `aisignoff freeze` records the levels of every line, so that they stay. `aisignoff diff origin/main` shows the levels of just the lines a change touches. See [Line by line](https://industrial-mathematics-group.github.io/aisignoff/history/).

## Folder report

The badges summarise the whole repository; `aisignoff report --tree` shows the level mix of every folder, and `aisignoff report --html report.html` writes an interactive page with a sunburst and a folder table, like a coverage report for AI use. See [Folder report](https://industrial-mathematics-group.github.io/aisignoff/report/) and [aisignoff's own](https://industrial-mathematics-group.github.io/aisignoff/signoff/).

## Example workflows

Copy one of these into `.github/workflows/` to check the declarations in CI (details in [Example workflows](https://industrial-mathematics-group.github.io/aisignoff/integration/)):

| File | What it does |
|---|---|
| [`signoff-lint.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-lint.yml) | fails when a file has no valid declaration, with the folder tree in the job summary and the folder report as an artifact |
| [`signoff-badges.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-badges.yml) | the same, plus README badges on a `badges` branch |
| [`signoff-pr-diff.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pr-diff.yml) | shows reviewers the declarations of the lines a pull request changes |
| [`signoff-pr-files.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pr-files.yml) | shows reviewers the declarations of the files a pull request changes |
| [`signoff-release.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-release.yml) | attaches the declarations of all files and the folder report to each GitHub release |
| [`signoff-pages.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pages.yml) | publishes the folder report to GitHub Pages |
| [`pre-commit-config.yaml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/pre-commit-config.yaml) | runs `aisignoff lint` before each commit, with [pre-commit](https://pre-commit.com) |

Repositories of the Industrial Mathematics Group use the organisation's ready-made workflows instead of the first two (*Actions → New workflow*).

## Documentation

**[industrial-mathematics-group.github.io/aisignoff](https://industrial-mathematics-group.github.io/aisignoff/)**, with:
- [the levels](https://industrial-mathematics-group.github.io/aisignoff/#the-levels);
- [the `SIGNOFF.toml` format](https://industrial-mathematics-group.github.io/aisignoff/signoff-toml/) and [inline tags](https://industrial-mathematics-group.github.io/aisignoff/inline-tags/);
- [line-by-line declarations from git history](https://industrial-mathematics-group.github.io/aisignoff/history/);
- [all commands](https://industrial-mathematics-group.github.io/aisignoff/commands/);
- [the folder report](https://industrial-mathematics-group.github.io/aisignoff/report/);
- [CI and badges](https://industrial-mathematics-group.github.io/aisignoff/ci/) and [example workflows](https://industrial-mathematics-group.github.io/aisignoff/integration/);
- [migrating from aidecl](https://industrial-mathematics-group.github.io/aisignoff/migrating/).

## License

[MIT](LICENSE)
