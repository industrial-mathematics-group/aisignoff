# AI review of <pull request or commit>

<!-- The report of an A2 or A3 review (docs/levels.md, "The record of a review"). Copy this file to
     reviews/pull<number>.md (or reviews/commit<hash>.md), fill it in and commit it with the change.
     This is a template to start from: aisignoff never reads a report, so a repository or organisation
     can use any form, and check it with a tool of its own. Keep the two lists apart in any form.
     Severities: trivial, minor, major, critical (docs/levels.md, "Severity").
     The reviewer only reviews: it reports what it found and changes nothing in the reviewed content. -->

- **Reviewer:** <model, and how it reviewed, e.g. "GPT Sol (OpenAI), new session without the generating conversation">
- **Reviewed:** <the change: pull request, commit or commit range>, on <date>
- **Level:** <A2 or A3>
- **Highest finding in this change:** <none, trivial, minor, major or critical>

<!-- The line above counts only the findings under "Findings in this change". The commit message or
     pull request description repeats it as "AI-Review-Findings: <the same word>". It blocks nothing:
     reports show it as the findings level of the lines the change lands (minor F1, major F2,
     critical F3), until a later review of those lines finds them fixed. -->

## Summary

<Two or three sentences: what the change does, and whether it holds up.>

## What was checked

<What the reviewer read and ran: the diff against the task, the tests, the documentation.>

## Findings in this change

<!-- Only what the change itself introduces or makes worse. "None." if there is nothing. -->

| # | Severity | Where | Finding |
|---|---|---|---|
| 1 | <severity> | <file:line> | <what is wrong, and why> |

## Outside this change

<!-- Problems the reviewer met that were there before the change and that it neither causes nor
     makes worse, of any severity. They don't count towards the highest finding. Say for each one
     why the change isn't its cause, so that a maintainer can check that quickly. "None." if there
     is nothing. -->

| # | Severity | Where | Problem | Why it isn't caused by this change |
|---|---|---|---|---|
| 1 | <severity> | <file:line> | <what is wrong> | <e.g. "unchanged since <commit>; the change doesn't touch this path"> |

## New evidence (A3 only)

<!-- What the reviewer produced, and where it is committed: new tests, benchmarks, scripts, a second
     derivation. Leave this section out of an A2 report. -->
