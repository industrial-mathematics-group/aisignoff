# aisignoff

**aisignoff records how each file, and each line, of a repository was made and checked:** how much an AI generated, how thoroughly a human reviewed it, and how thoroughly an AI reviewed it. `aisignoff lint` checks those declarations in CI, the way a test suite checks code.

```bash
pipx install aisignoff
aisignoff init -g G0 -H H2 -a A0 --reviewed-by "Jane Doe"
aisignoff lint
```

## What it is for

Research code, analysis scripts, papers and data are increasingly written with AI help. Readers, reviewers and co-authors need to know which parts were, and what was done to check them. aisignoff makes that a property of the repository, kept next to the code:

- **Declare** each file once in [`SIGNOFF.toml`](files.md) or in a header comment, and let each pull request [declare its own lines](history.md) through its description.
- **Check** in CI that nothing is undeclared, incomplete or below the repository's [minimum levels](levels.md#minimum-levels).
- **Show** the result: README [badges](report.md#badges), a [folder report](report.md#the-interactive-report) like a coverage report, and the levels of just the lines a pull request changes ([`aisignoff diff`](report.md#the-lines-of-a-change-aisignoff-diff)).

It works like [REUSE](https://reuse.software) does for licences. The name is meant both ways: the AI signs off, and so does the human ("ai", said in German, sounds like "I"). A declaration is a statement someone signs off on, not a cryptographic signature.

## The levels in one table

Every file or line gets one level on each of three axes:

| | Generation | Human review | AI review |
|---|---|---|---|
| **0** | **G0** Human | **H0** Plausibility check | **A0** None |
| **1** | **G1** AI-assisted | **H1** Tested | **A1** Self-check by the generating session |
| **2** | **G2** AI-generated | **H2** Reviewed line by line | **A2** Review by a new session |
| **3** | **G3** AI-autonomous | **H3** Independently validated | **A3** Extensive review or benchmark by a different model |

The rules that go with them are on [Levels and rules](levels.md).

## Files or lines

aisignoff works at two depths, and you can start with the first:

- **File level.** `SIGNOFF.toml` maps paths to levels: a default for `**`, exceptions for folders and globs. Files can also carry the levels in a header comment. This needs nothing but the file, and suits results, data, notebooks and papers. See [Declaring files](files.md).
- **Line level.** With `[history]` in `SIGNOFF.toml`, each line takes the declaration of the commit that landed it on the default branch, which for a pull request is its description. A pull request that changes 35 lines of an 800-line file changes the levels of those 35 lines. The file-level declarations stay as the fallback. See [Declaring lines](history.md).

## Where to go next

- [Quick start](getting-started.md): from nothing to a checked repository.
- [Declaring lines](history.md): the declaration model with `[history]`, and [snapshots](snapshots.md) that keep it stable.
- [CI and workflows](ci.md): checks, pull request descriptions, merge methods, merge queues.
- [Reports](report.md): summaries, the folder report, `diff` and badges.
- Reference: [commands](commands.md), [`SIGNOFF.toml`](signoff-toml.md), [compatibility](compatibility.md), [changelog](changelog.md).
