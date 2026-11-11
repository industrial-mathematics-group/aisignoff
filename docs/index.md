# aisignoff

**Declare and check how each file in a repository was created and reviewed.** Every file gets three levels:

- **G0–G3:** how much an AI generated;
- **H0–H3:** how thoroughly a human reviewed it;
- **A0–A3:** how thoroughly an AI reviewed it.

It works like [REUSE](https://reuse.software) does for licences: a path-based [`SIGNOFF.toml`](signoff-toml.md), optional [tags in file headers](inline-tags.md), and a `lint` command for [CI](ci.md).

!!! note "The name"
    It's meant both ways: the AI signs off on what it generated or reviewed, and so does the human ("ai", said in German, sounds like "I"). It's a declaration you sign off on, not a cryptographic signature.

```bash
pipx install aisignoff
aisignoff init -g G0 -H H2 -a A0 --reviewed-by "Jane Doe"
aisignoff lint
```

See [Getting started](getting-started.md) for a full walkthrough.

## The levels

The levels come from the [AI policy](https://github.com/industrial-mathematics-group/.github/blob/main/.github/CONTRIBUTING.md#ai-assisted-contributions) of the Industrial Mathematics Group:

| | Generation | Human review | AI review |
|---|---|---|---|
| **0** | **G0** Human | **H0** Plausibility check | **A0** None |
| **1** | **G1** AI-assisted | **H1** Tested | **A1** Self-check by the generating session |
| **2** | **G2** AI-generated | **H2** Reviewed line by line | **A2** Review by a new session |
| **3** | **G3** AI-autonomous | **H3** Independently validated | **A3** Extensive review or benchmark by a different model |

Two rules always apply:

- **AI-written content must be checked:** G1–G3 need at least A1.
- **Human-written content has no self-check:** G0 can't be A1, since there is no generating session. Any AI review of it is A2 or A3.

A repository can require more through a [policy](signoff-toml.md#minimum-levels).

## Files and pull requests

aisignoff declares **files**. It complements the declaration in **pull requests**, where the same levels are ticked in the PR template:

| | PR declaration | `SIGNOFF.toml` |
|---|---|---|
| Describes | each **change** merged into `main` | the **current state** of every file |
| Good for | code developed through pull requests | results, data, notebooks, papers, single-commit uploads |
| Checked by | the *PR-signoff* check | `aisignoff lint` (the *File-signoff* check) |

Both use the same keys, so the job summary of the PR check can be copied into `SIGNOFF.toml`.

With [`[history]`](history.md), the two come together: the pull request's declaration lands in git with its squash or merge commit (as trailers, or the ticked boxes of the pull request template), and aisignoff declares each line by the commit that brought it in. `SIGNOFF.toml` then holds the defaults, the files without lines, and attestations that re-declare whole files after a review.
