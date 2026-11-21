# aisignoff guide for the developing agent (aisignoff {{version}})

You wrote or changed content in a repository that uses aisignoff. Your job is to declare honestly
how the change was made, and to leave the reviews to the reviewers. aisignoff records three levels
per file and per line: AI generation (G0-G3), human review (H0-H3) and AI review (A0-A3).
`aisignoff lint` checks the declarations in CI.

## What you declare

- **Generation: your level.** The highest level of any substantial part of the change:
  - **G1** AI-assisted: a person wrote it, you suggested or edited parts.
  - **G2** AI-generated: you wrote substantial parts, a person steered step by step and edited.
  - **G3** AI-autonomous: you produced it largely end to end from a goal, an issue or a short instruction.
- **Assisted-by: your model,** with its vendor, for example `Claude Opus 5.5 (Anthropic)`.
  Name every model that wrote a substantial part.
- **Human review: not yours.** Leave it to the person who reviews: `Human-Review: TODO` (or the
  H boxes of the template unticked). Never tick H0-H3 and never write a `Reviewed-by` yourself.
- **AI review: A0.** Your own tests, rereading and self-checks are part of generating, not a
  review. Never declare A1, A2 or A3 for a review you did, and never declare one that hasn't
  happened yet.

## What you never write

- **Findings.** `AI-Review-Findings:` belongs to an independent reviewer. Leave it empty. When a
  review has happened, copy its result exactly as the reviewer gave it: the level (A1-A3), the
  `AI-Reviewed-by` text and the findings word. Never lower, guess or reword a finding.
- **Review records for yourself:** no `aisignoff attest`, no `[[commits]]` entry and no annotation
  that raises Human-Review or AI-Review.
- **`SIGNOFF.toml`: never.** It is the file a person signs off: the rules, a person's reviews and
  the generations only a person can give. (Without `[history]`, `aisignoff annotate` with
  `-H TODO` is the one exception, see below.)
- **The review folder** (`reviews/` unless `[review] dir` says otherwise): never modify or delete a
  file there. It holds the reviewers' records; a change that edits one fails `lint`.

## When a landed commit is declared wrong

Don't correct it yourself: a `[[commits]]` entry is a person's word, in `SIGNOFF.toml`. Tell the
person responsible which commit it is and what you think it should say.

## Where the declaration goes

| The repository | Declare in |
|---|---|
| `[history]` on, pull requests merged or squashed | the pull request description: the ticked boxes of its template, or "Key: value" lines. One form per description, never both |
| `[history]` on, rebase merges or direct commits | every commit message, as "Key: value" lines |
| no `[history]` | `SIGNOFF.toml`, with `aisignoff annotate PATH -g G3 -H TODO -a A0 --assisted-by "<model>"` for the files you added or changed |

"Key: value" lines, anywhere in the message body (not in a code block):

```
AI-Generation: G3
Human-Review: TODO
AI-Review: A0
Assisted-by: Claude Opus 5.5 (Anthropic)
```

On a pull request's branch, commit messages need no declaration: only an `AI-Generation:` line is
read there, and only to raise the generation of the lines that commit wrote.

## After an independent review

- The reviewer reports and changes nothing; the fixes are yours, in this change or a later one.
- Lines you change after a review go back to F- (unreviewed) until the next review. That is
  expected: don't declare the old review for the new lines. You never clear a finding: the next
  review attests your fix and the change it fixed, and sets their findings.
- A review with findings is still mergeable. A finding is recorded and shown, never a threshold.

## Check before you push

```bash
aisignoff lint                                                   # the repository as it is
aisignoff lint --declare-from description.md --base origin/main  # with [history]: the pull request
```

`lint` fails on a `TODO` until the person fills it in. That is the human signoff, not your error.

Full rules: https://industrial-mathematics-group.github.io/aisignoff/levels/
