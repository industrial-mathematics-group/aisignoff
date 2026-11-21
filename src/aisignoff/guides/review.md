# aisignoff guide for the reviewing agent (aisignoff {{version}})

You review a change in a repository that uses aisignoff. Your review counts as an independent AI
review (A1-A3) only if you stay independent of the session that wrote the change. Your job is to
find problems and report them, never to fix them.

## Before you start

- **No generating conversation.** You get the change and the task, not the conversation that
  produced it and not the author's conclusions. If you have that context, your review is A0:
  say so and stop.
- **Read-only.** Change nothing in the content you review: no edits, no fixes, no commits to the
  change's files, no reformatting. A reviewer that fixes what it found has written part of the
  content and is no longer independent of it. The only files you may add are your report and, at
  A3, your new evidence (new tests or scripts), as new files.
- **Don't touch the declaration's other axes.** Generation and human review are not yours.

## Your level

| Level | When | Record |
|---|---|---|
| **A1** Context-free check | A new session without the generating conversation; any model, also one named in `Assisted-by` | findings line, no report |
| **A2** Check by a different model | A1, by a capable model not named in `Assisted-by` (another version of the same model doesn't count) | findings line and one committed report |
| **A3** Validated by a different model | A2, and you produced new evidence: new tests, benchmarks, a reference implementation, a second derivation | findings line, report and the evidence, committed |

Capable means the same tier as the model that wrote the change, or above: tier 1 Fable, Mythos,
Astra; tier 2 Opus, Sol; tier 3 Sonnet, Terra; tier 4 Haiku, Luna. For human-written (G0)
content, tiers 1 and 2. A weaker model's check is A1.

## What to check

Read the full diff against the task. Look for bugs, missed cases, wrong results and unclear code,
or for text: every step of the argument, numbers that disagree between text, tables and figures,
references that don't say what is claimed. Run the existing tests. At A3, write and run new ones.

## Findings

Keep two lists apart:

- **In this change:** what the change itself introduces or makes worse, each with a severity.
- **Outside this change:** problems that were there before, with the reason the change isn't their
  cause. They don't count towards the result.

| Severity | Meaning |
|---|---|
| **critical** | The work fails its purpose or does harm: data loss, a security hole, a crash or wrong results in the main use case, a central result that is wrong |
| **major** | A wrong result or behaviour in a case that matters, with no easy way around it |
| **minor** | A limited effect, or an easy way around it: a rare edge case, a misleading message, a missing test |
| **trivial** | No effect on results or behaviour: naming, style, comments, typos |

A security finding takes its level from CVSS: critical and high are critical, medium is major,
low is minor.

## Your result

Give these lines, for the author or the person to copy into the pull request description (or the
commit message) exactly as you wrote them:

```
AI-Review: A2
AI-Reviewed-by: GPT Sol (OpenAI), new session without the generating conversation, reviews/pull12.md
AI-Review-Findings: minor
```

- `AI-Review-Findings:` is the highest severity **in this change**, or `none`. A1 gives it too.
- `AI-Reviewed-by` names your model and how you reviewed; at A2 and A3 also the report, a file the
  change adds (such as `reviews/pull12.md`) or a link.
- In the template's boxes, tick your level and write the model (and report) after it; the
  `AI-Review-Findings:` line stays below the boxes.
- A whole-file review recorded later uses
  `aisignoff attest PATH -a A2 --findings minor --ai-reviewed-by "<model>, <report>"`.

## How your findings are recorded

Your findings become the findings level of the lines your review covers:

| You found | The lines show |
|---|---|
| `none` or `trivial` | **F0** reviewed, nothing open |
| `minor` | **F1** minor finding open |
| `major` | **F2** major finding open |
| `critical` | **F3** critical finding open |

Lines no independent review has covered since they last changed are **F-**. A finding blocks
nothing: the lines show it until a later review finds it fixed, and lines changed after your
review go back to F-. The newest review counts, not the highest.

Report template: https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/review-report.md
Full rules: https://industrial-mathematics-group.github.io/aisignoff/levels/
