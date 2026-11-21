# Levels and rules

The levels come from the [AI policy](https://github.com/industrial-mathematics-group/.github/blob/main/.github/CONTRIBUTING.md#ai-assisted-contributions) of the Industrial Mathematics Group. A declaration gives one level per axis, plus the names behind it.

## The three axes

| Axis | Key | Levels | Names key |
|---|---|---|---|
| Generation | `AI-Generation` | **G0** Human · **G1** AI-assisted · **G2** AI-generated · **G3** AI-autonomous | `Assisted-by`: the AI tools and models that wrote it |
| Human review | `Human-Review` | **H0** Plausibility check · **H1** Tested · **H2** Reviewed line by line · **H3** Independently validated | `Reviewed-by`: the responsible human |
| AI review | `AI-Review` | **A0** No independent AI review · **A1** Context-free check · **A2** Check by a different model · **A3** Validated by a different model | `AI-Reviewed-by`: the reviewing model, and how |

For generation, declare the highest level of any substantial part. The two review axes are cumulative: a level says that everything below it was done too, so declare the highest one completed.

## Generation: G0 to G3

From G2 on, the generating AI is expected to check its own work: run the tests, reread the result. That is part of generating, not an AI review.

| Level | Meaning | Code | Research and writing |
|---|---|---|---|
| **G0** Human | Written by a person, without AI | Typed by a person. Formatters, linters and code generators that follow fixed rules don't count | Text, derivations, analysis and figures by a person. Spelling and grammar tools don't count |
| **G1** AI-assisted | A person wrote it; AI suggested or edited parts | Completions; a function or fix suggested in a chat and adapted; an AI refactoring of code a person wrote | AI polished the language, suggested a structure, a proof idea or literature. The argument, the numbers and the wording are the author's |
| **G2** AI-generated | AI wrote substantial parts; a person directed the work step by step and edited the result | AI wrote functions or modules to a person's design, over several rounds the person steered | AI drafted sections, carried out a derivation, wrote the analysis script or made a figure. The person set the question and the method |
| **G3** AI-autonomous | An agent produced it largely end to end from a goal | An agent implemented a feature with its tests from an issue or a short instruction | An agent ran the study: chose the method, ran the computations and wrote it up |

## Human review: H0 to H3

`Reviewed-by` names the person who did the review and is responsible for the content.

| Level | Meaning | Code | Research and writing |
|---|---|---|---|
| **H0** Plausibility check | A named person takes responsibility and has looked at the result as a whole: it does what was asked and looks plausible | Read the description and skimmed the change; the checks are green; the behaviour looks right | Read the summary and the main results; magnitudes, units and trends are plausible |
| **H1** Tested | H0, and ran it or reproduced the key results in person, and read the important parts | Ran the tests and the main use case; read the core logic and the public interface | Reran the script or recomputed the key numbers; checked the central step of the argument; checked that the key references exist and say what is claimed |
| **H2** Reviewed line by line | H1, and read and understood every line | Every changed line, tests included; edge cases and error paths thought through | Every sentence, formula and proof step; every reference; every figure and table against its data |
| **H3** Independently validated | H2, and confirmed by means that don't depend on the work itself | Own new tests, a benchmark or a reference implementation; or a second person's line-by-line review | The result reproduced another way (another ansatz, other code, a known limit); or checked by a second qualified person |

## AI review: A0 to A3

The AI review axis counts only review that is independent of the session that wrote the content. Each level is the one below it plus one more kind of independence. `AI-Reviewed-by` names the reviewing model and how it reviewed; for A2 and A3 also where the record is.

| Level | Meaning | Code | Research and writing |
|---|---|---|---|
| **A0** No independent AI review | Nothing, or only the generating session's own checks | The agent ran its own tests; or no AI looked at it | The session reread its own draft; or no AI looked at it |
| **A1** Context-free check | A new session reviewed the whole change without the generating conversation | Reads the full diff against the task; looks for bugs, missed cases and unclear code; runs the existing tests | Reads the full text; checks each step of the argument, that numbers agree between text, tables and figures, and that references exist |
| **A2** Check by a different model | A1, done by a different, capable model, which commits a review report | As A1, and the report | As A1, and the report |
| **A3** Validated by a different model | A2, and the reviewer produced new evidence and commits it with the report | Writes and runs new tests, edge cases or benchmarks, or compares with a reference implementation. The new tests and scripts are committed | Recomputes or derives the result another way, recreates plots with another method, proves it with a different ansatz, or searches for counterexamples. The scripts and derivations are committed |

The terms:

- **Context-free:** the reviewer gets the content and the task, not the generating conversation and not the author's conclusions. A subagent with a fresh context counts. A second model that reviews inside the generating conversation, with its context, doesn't: that is A0.
- **Different model:** a model that is not named in `Assisted-by`. Another model of the same vendor counts (Fable reviewing Opus); another version of the same model doesn't. For G0 content, every model is a different one.
- **Capable:** in the same tier as the model that wrote the content, or above; for G0 content, in the two top tiers ([Model tiers](#model-tiers)). A check by a weaker model counts as A1.

### The record of a review

- **A2: one report,** with only the results. It is committed with the change (for example `reviews/pull12.md`) or linked.
- **A3: everything.** The same report, and with it what the reviewer produced: the new tests, benchmarks, scripts or derivations.
- **A1** needs no report, but gives its findings like A2 and A3 ([below](#the-record-of-a-review)), so that a check by the same model is a reference for what a different model finds.

**The reviewer only reviews.** It reports what it found and changes nothing in the content it reviews: a reviewer that fixes what it found has written part of the content, so it is no longer independent of it, and the next review would need yet another model. The fixes are the author's, in the same change or a later one, and a later review checks them.

What a report looks like is up to the repository or its organisation, and so is checking it: aisignoff never reads one. [`examples/review-report.md`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/review-report.md) is a template to start from. Whatever the form, a report should keep two things apart:

- **Findings in this change:** what the change itself introduces or makes worse, each with its severity ([below](#severity)).
- **Outside this change:** problems the reviewer met that were there before, of any severity, each with the reason why the change isn't its cause. They don't count towards the highest finding. A maintainer reads this part to see that it really is separate.

The declaration carries everything aisignoff needs to know about the review. `AI-Reviewed-by` names the model and the report, such as `GPT Sol (OpenAI), reviews/pull12.md`. A line `AI-Review-Findings:` gives the highest severity among the findings in this change, or `none`:

```
AI-Review: A2
AI-Reviewed-by: GPT Sol (OpenAI), reviews/pull12.md
AI-Review-Findings: minor
```

A review of A1 gives the same line, without a report: `AI-Reviewed-by` names the model and how it reviewed, such as `Claude Opus 5.5 (Anthropic), new session`. What a context-free check by the model that wrote the content finds is the reference for the findings of a different model at A2 and A3.

In a pull request template, the same line stands below the AI review boxes. It belongs to A1, A2 and A3: next to A0 it isn't read, so it can be left empty or say `n/a`. With several such lines, the most severe value counts. The reports themselves are in the [review folder](history.md#the-review-folder) (`reviews/`), which needs no declaration.

A review can also land later, in a pull request of its own that only adds files to the review folder: its report and a record file that names what it reviewed, whole files or the lines of a commit. Such a pull request declares nothing, and no change may modify or delete an earlier review's files ([The review folder](history.md#the-review-folder)).

A finding is recorded, not a threshold: a change with a major finding can be merged, and its lines show the finding until a later review finds it fixed ([Findings](#findings-f0-to-f3)).

### Severity

| Severity | Meaning | Code | Research and writing |
|---|---|---|---|
| **critical** | The work fails its purpose, or does harm | Data loss or corruption, a security hole, a crash or wrong results in the main use case | A central result or conclusion is wrong; a proof fails; data are misused |
| **major** | A wrong result or behaviour in a case that matters, with no easy way around it | A wrong result for a supported input; a broken feature; a missing check that lets invalid input through | A wrong number, formula or figure that a reader would rely on; a gap in an argument; a reference that doesn't say what is claimed |
| **minor** | A limited effect, or an easy way around it | A wrong result in a rare edge case; a misleading error message; a missing test | An imprecise statement; an inconsistency between text and table that doesn't change a result |
| **trivial** | No effect on results or behaviour | Naming, style, comments, typos | Wording, layout, typos |

The four levels follow the severity of IEEE Std 1044-2009, the standard classification for software anomalies (critical, major, minor, inconsequential; its "blocking" counts as critical here) and of bug trackers such as Bugzilla. A security finding takes its level from its [CVSS](https://www.first.org/cvss/) rating: critical and high are critical, medium is major, low is minor.

What `lint` checks:

- **Before the merge** ([`lint --declare-from`](ci.md#checking-the-pull-request-description)), a description that declares A1, A2 or A3 needs the line `AI-Review-Findings:` with `none` or a severity. A2 and A3 also need their report: `AI-Reviewed-by` names the reviewing model and then a link or a file inside the repository that the change adds. A report that was there before, such as an earlier review's, doesn't count, and a change that modifies or deletes a file of the review folder fails. Nothing is read from the report.
- **A record file** in the review folder is checked the same way, for each entry: its findings, and for A2 and A3 a report that exists or a link.
- **Any severity passes.** An invalid value (`AI-Review-Findings: high`) fails, in a pull request description and in a landed commit's message.
- A landed commit with a line that looks like the findings line but isn't (`AI-Review-Finding:`) gets a warning (`lint --strict` fails on it): its lines stay at F-.
- With `merge-method = "rebase"`, the description lands nowhere and isn't checked, and commit messages need neither the line nor the report. In a repository still on `version = 3`, the line and the report are checked for the ticked boxes of today's template, not for trailers on the old scale.

aisignoff doesn't read the findings themselves: whether one was rated correctly, and whether it really lies outside the change, stays with the people who declare it.

## Findings: F0 to F3

Reports show a fourth axis next to the three that are declared: what the last independent AI review of a line found. No one declares it as such; it follows from the `AI-Review-Findings:` lines of the reviews.

| Level | Meaning |
|---|---|
| **F-** Not reviewed | No independent AI review (A1, A2 or A3 with its findings) has covered the line since it last changed. The default |
| **F0** Reviewed, nothing open | The last review found nothing in the change, or only trivial findings |
| **F1** Minor finding open | The last review found a minor problem |
| **F2** Major finding open | The last review found a major problem |
| **F3** Critical finding open | The last review found a critical problem |

The findings are a state of the code, not of the pull request:

- **A review sets the lines it covered.** The commit that lands a change with an A1, A2 or A3 review gives its findings to the lines it lands. An [attestation](history.md#raising-a-review-attestations) of A1, A2 or A3 with `--findings` gives them to every line of the file it attests, or with `--commit` to the lines one commit landed, and a [`[[commits]]` entry](history.md#correcting-a-commit) can restate them with `AI-Review-Findings`. In file-level declarations, an annotation can give them with the same key.
- **A change without a review changes nothing else.** Lines it doesn't touch keep the findings of the last review that covered them, just as they keep their human and AI review levels.
- **What a later change touches goes back to F-,** because new code hasn't been reviewed. A fix therefore becomes unreviewed, never silently clean. Only the next review can set F0: one that attests the commit with the finding and the fix together sets all their lines ([Fixing a finding](history.md#the-review-folder)).
- **The newest review counts,** not the highest level: an attestation after the commit replaces the commit's findings for the lines it covers. Newest means of the newest content: an attestation `--at` an older commit, recorded after a review of the current file, doesn't replace that review's findings. A0 has no findings, and an A1–A3 review without them (such as an A1 commit from before A1 gave findings) leaves them as they are; a commit without them leaves the lines it lands at F-.

F- (unreviewed) and F2 or F3 (a known open problem) are the two that need attention: the [report](report.md#the-interactive-report) shows both as figures at the top. The findings are per line as far as the review's commit or attestation reaches; a finding that names its lines can't narrow them further, since aisignoff never reads the report.

### Model tiers

A guideline as of November 2026, with names only: a newer version of a name stays in its tier until the table changes. Each team decides what it counts as capable, places the models that aren't listed, and says so in its own rules.

| Tier | Claude (Anthropic) | ChatGPT (OpenAI) | Capable reviewer for |
|---|---|---|---|
| 1 | Fable, Mythos | Astra | everything |
| 2 | Opus | Sol | content written by tier 2 to 4, and G0 |
| 3 | Sonnet | Terra | content written by tier 3 or 4 |
| 4 | Haiku | Luna | content written by tier 4 |

The rows pair each vendor's lineup by position, its most capable model first, not by a benchmark. With several models in `Assisted-by`, the highest one counts.

## What a valid declaration needs

| Key | Needed |
|---|---|
| `AI-Generation`, `Human-Review`, `AI-Review` | always |
| `Reviewed-by` | always (every level of human review has a responsible person) |
| `Assisted-by` | for G1–G3; not allowed with G0 |
| `AI-Reviewed-by` | for A1–A3; not allowed with A0 |

`lint` also fails on two declarations that contradict the definitions:

- **A self-check is A0.** A1–A3 whose `AI-Reviewed-by` names only a self-check, the same session or the generating session.
- **A2 and A3 need a different model.** A2 or A3 whose `AI-Reviewed-by` names only models from `Assisted-by`. A new session of a model that wrote the content is A1.

aisignoff compares model names by their words, without the vendor in brackets and without version numbers: `Claude Opus 5.5 (Anthropic)` and `Opus` name a model that `Claude Opus (Anthropic)` wrote with, and `Claude Fable` doesn't. It doesn't check tiers: whether a reviewer is capable, and whether a review was context-free, stays with the people who declare it.

No level of generation requires an AI review by itself. A repository that wants one sets a minimum. The [findings](#findings-f0-to-f3) are never a minimum: they are shown, and block nothing.

## Minimum levels

A repository can require more with a `[policy]` table in `SIGNOFF.toml`:

```toml
[policy]
"*" = { human = "H1" }               # every file
G3  = { human = "H2", ai = "A1" }    # AI-autonomous content needs more
```

- `"*"` is the default for every generation level; `G0`–`G3` override it key by key.
- `human` takes H0–H3, `ai` takes A0–A3, and both mean the same for every generation level.
- The `"*"` minimum also applies to a declaration whose generation is missing or `TODO`.

`lint` fails on any file or line below the policy.

## TODO: left for a person

Any level or name may be `TODO`. An AI agent that declares its own work can leave the human review to the person who will do it:

```bash
aisignoff annotate src/solver.py -g G3 -H TODO -a A0 \
    --assisted-by "Claude Opus 5.5 (Anthropic)"
```

`-H TODO` without `--reviewed-by` writes `Reviewed-by` as `TODO` too. The axes that are filled in are still checked, and `lint` fails until every `TODO` is replaced.

## How reports count an axis

[Reports](report.md) and badges count each axis on its own. An axis is *undeclared* when its level is missing, `TODO` or invalid, or when an error is about that axis (a missing name, a level below the policy). An error about one axis leaves the other two as declared.
