# aisignoff

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24020702.svg)](https://doi.org/10.5281/zenodo.24020702)
[![PyPI](https://img.shields.io/pypi/v/aisignoff.svg)](https://pypi.org/project/aisignoff/)
[![Docs](https://img.shields.io/badge/docs-online-9558B2.svg)](https://industrial-mathematics-group.github.io/aisignoff/)

[![AI generation](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/badges/aisignoff-generation.json)](https://industrial-mathematics-group.github.io/aisignoff/signoff/)
[![Human review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/badges/aisignoff-human-review.json)](https://industrial-mathematics-group.github.io/aisignoff/signoff/)
[![AI review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/badges/aisignoff-ai-review.json)](https://industrial-mathematics-group.github.io/aisignoff/signoff/)

**aisignoff records how each file, and each line, of a repository was made and checked:** how much an AI generated (G0–G3), how thoroughly a human reviewed it (H0–H3), and how thoroughly an AI reviewed it (A0–A3). `aisignoff lint` checks those declarations in CI.

It works like [REUSE](https://reuse.software) does for licences: a path-based `SIGNOFF.toml`, optional tags in file headers, and a `lint` command. With `[history]`, each pull request declares exactly the lines it changes, with its description. The name is meant both ways: the AI signs off, and so does the human ("ai", said in German, sounds like "I"). It's a declaration, not a cryptographic signature.

## Install

```bash
pipx install aisignoff        # or: uv tool install aisignoff, or: pip install aisignoff
```

Requires Python 3.11 or newer and git; no other dependencies.

## Quick start

```bash
# a default for everything: written by a human, reviewed line by line, no AI review
aisignoff init -g G0 -H H2 -a A0 --reviewed-by "Jane Doe"

# what is different, by file, folder or glob (the last matching annotation wins)
aisignoff annotate results/ -g G2 -H H1 -a A1 \
    --assisted-by "Claude Opus 5.5 (Anthropic)" \
    --ai-reviewed-by "Claude Opus 5.5 (Anthropic), self-check by the generating session" \
    --reviewed-by "Jane Doe"

# every file declared correctly?
aisignoff lint
```

Then add [`signoff-lint.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-lint.yml) to `.github/workflows/` and require its check on the default branch. To let pull requests declare their own lines, add `[history]` to `SIGNOFF.toml`: see the [quick start](https://industrial-mathematics-group.github.io/aisignoff/getting-started/).

## Documentation

**[industrial-mathematics-group.github.io/aisignoff](https://industrial-mathematics-group.github.io/aisignoff/)**:

- [Levels and rules](https://industrial-mathematics-group.github.io/aisignoff/levels/): what G, H and A mean and what each requires
- [Declaring files](https://industrial-mathematics-group.github.io/aisignoff/files/): `SIGNOFF.toml` annotations and inline tags
- [Declaring lines](https://industrial-mathematics-group.github.io/aisignoff/history/): one owner per line, pull request descriptions, `[[commits]]` and attestations
- [Snapshots](https://industrial-mathematics-group.github.io/aisignoff/snapshots/): `aisignoff freeze`, so that levels stay
- [CI and workflows](https://industrial-mathematics-group.github.io/aisignoff/ci/): example workflows, merge methods, merge queues, pre-commit
- [Reports](https://industrial-mathematics-group.github.io/aisignoff/report/): the folder report ([aisignoff's own](https://industrial-mathematics-group.github.io/aisignoff/signoff/)), `aisignoff diff` and badges
- [Command reference](https://industrial-mathematics-group.github.io/aisignoff/commands/), [`SIGNOFF.toml` reference](https://industrial-mathematics-group.github.io/aisignoff/signoff-toml/), [changelog](https://industrial-mathematics-group.github.io/aisignoff/changelog/)

## License

[MIT](LICENSE)
