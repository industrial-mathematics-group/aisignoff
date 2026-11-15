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

- **A2: one report.** Exactly one Markdown file, committed with the change (for example `reviews/2026-11-15-solver.md`), with only the results: what was reviewed and how, the findings with their severity, the fixes made for them, and the problems left open. No other files.
- **A3: everything.** The same report, and with it what the reviewer produced: the new tests, benchmarks, scripts or derivations.
- **A1** needs no record.

A report lists its findings one per list item or heading that starts with the severity ([below](#when-a-review-counts)), so that `lint` can read them:

```markdown
## Findings

- **minor:** the error message names the wrong file. Fixed in 3f1c9e0.
- **trivial:** two typos in the docstring. Fixed.

## Open problems

- **minor:** no test covers an empty input.
```

`**severity:**`, `[severity]` and `severity:` all count, in any case, as do numbered items and headings (`### [minor] …`). Fenced code blocks don't.

`AI-Reviewed-by` names the report, such as `GPT Sol (OpenAI), new session, reviews/2026-11-15-solver.md`. `exclude = ["reviews/**"]` in `SIGNOFF.toml` keeps the reports themselves out of the declarations.

### When a review counts

A review counts once each of its findings is fixed or listed as open in its record. A fix for a small finding needs no review of its own. A severe finding ends the review: it is fixed, the change is reviewed again, and the new report replaces the old one. What is severe is set per repository, on this scale:

| Severity | Meaning | Code | Research and writing |
|---|---|---|---|
| **critical** | The work fails its purpose, or does harm | Data loss or corruption, a security hole, a crash or wrong results in the main use case | A central result or conclusion is wrong; a proof fails; data are misused |
| **major** | A wrong result or behaviour in a case that matters, with no easy way around it | A wrong result for a supported input; a broken feature; a missing check that lets invalid input through | A wrong number, formula or figure that a reader would rely on; a gap in an argument; a reference that doesn't say what is claimed |
| **minor** | A limited effect, or an easy way around it | A wrong result in a rare edge case; a misleading error message; a missing test | An imprecise statement; an inconsistency between text and table that doesn't change a result |
| **trivial** | No effect on results or behaviour | Naming, style, comments, typos | Wording, layout, typos |

The four levels follow the severity of IEEE Std 1044-2009, the standard classification for software anomalies (critical, major, minor, inconsequential; its "blocking" counts as critical here) and of bug trackers such as Bugzilla. A security finding takes its level from its [CVSS](https://www.first.org/cvss/) rating: critical and high are critical, medium is major, low is minor.

By default the threshold is **major**: a major or critical finding needs a new review, and fixes for minor and trivial findings need none. A repository can move the threshold, and say where its reports are:

```toml
[review]
recheck = "major"        # trivial, minor, major (the default) or critical
reports = "reviews/**"   # the Markdown files that are review reports (the default)
```

`lint` enforces it: **a committed report that lists a finding from the threshold on fails**, fixed or not. So such a finding can't be merged with the review that found it. The way out is the rule itself: fix the finding, have the change reviewed again in a new session, and commit that review's report in place of the old one. The new report then lists at most smaller findings. A finding that turns out to be less severe is corrected in the report by the reviewer, not by the author.

aisignoff reads the severity each report gives. Whether a finding was rated correctly, and whether a new review was really done, stays with the people who declare it.

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

- **A self-check is A0.** A1–A3 whose `AI-Reviewed-by` names only a self-check of the generating session.
- **A2 and A3 need a different model.** A2 or A3 whose `AI-Reviewed-by` names only models from `Assisted-by`. A new session of a model that wrote the content is A1.

aisignoff compares the names as they are written, so it can't tell two versions of a model apart, and it doesn't check tiers: whether a reviewer is capable, and whether a review was context-free, stays with the people who declare it.

No level of generation requires an AI review by itself. A repository that wants one sets a minimum.

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
