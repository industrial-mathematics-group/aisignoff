# AI review of <pull request or commit>

<!-- The report of an A2 or A3 review (docs/levels.md, "The record of a review"). Copy this file to
     reviews/pull<number>.md (or reviews/commit<hash>.md), fill it in and commit it with the change.
     Keep the headings and the "Highest finding" line: `aisignoff lint` reads them before the merge.
     Severities: trivial, minor, major, critical (docs/levels.md, "When a review counts"). -->

- **Reviewer:** <model, and how it reviewed, e.g. "GPT Sol (OpenAI), new session without the generating conversation">
- **Reviewed:** <the change: pull request, commit or commit range>, on <date>
- **Level:** <A2 or A3>
- **Highest finding in this change:** <none, trivial, minor, major or critical>

<!-- The line above counts only the findings under "Findings in this change". The commit message or
     pull request description repeats it as "AI-Review-Findings: <the same word>". From the severity
     of [review] recheck on (by default major), the finding is fixed and the change reviewed again:
     the report of that review replaces this one. -->

## Summary

<Two or three sentences: what the change does, and whether it holds up.>

## What was checked

<What the reviewer read and ran: the diff against the task, the tests, the documentation.>

## Findings in this change

<!-- Only what the change itself introduces or makes worse. "None." if there is nothing. -->

| # | Severity | Where | Finding | Status |
|---|---|---|---|---|
| 1 | <severity> | <file:line> | <what is wrong, and why> | <fixed in <commit>, or open> |

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
