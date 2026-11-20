# CI and workflows

## The basic check

`aisignoff lint` exits with `0` when every file (and, with `[history]`, every line) has a valid declaration, `1` when something is missing, invalid or below the policy, and `2` on a usage or configuration error. Run it on every push and pull request:

```yaml
name: aisignoff

on:
  push:
    branches: [main]
  pull_request:
  merge_group:        # with a merge queue

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # the whole history, for [history]
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "aisignoff==1.0.0rc9"
      - run: aisignoff lint
```

Then require the check in the branch protection of the default branch, so no undeclared file is merged. Pin the version, so that a new release can't change your check unannounced, and raise the pin when you update.

With [line-level declarations](history.md), check out the whole history (`fetch-depth: 0`). That also fetches the default branch, which aisignoff needs to tell which lines have landed. Without `[history]`, a shallow checkout is enough.

`lint --strict` also fails on warnings: annotations that match no file (for example after a rename), undeclared reverts, `git pull` merges and commits that look like pull requests, and attestations that can't count.

## Checking the pull request description

In a pull request's run, its own lines haven't landed yet: its description will declare them when it lands, so they fail nothing on their own. To fail a pull request whose description is incomplete, pass the description to `lint`:

```yaml
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]   # run again when the description is edited

# … in the job, after the checkout:
      - name: Check the pull request's declaration
        if: github.event_name == 'pull_request'
        env:
          DESCRIPTION: ${{ github.event.pull_request.body }}
          AUTHOR: ${{ github.event.pull_request.user.login }}
        run: |
          printf '%s\n' "$DESCRIPTION" > "$RUNNER_TEMP/description.md"
          aisignoff lint --declare-from "$RUNNER_TEMP/description.md" --author "$AUTHOR" --base HEAD^1
```

- `--declare-from` reads the description exactly as the merge or squash commit's message will be read: "Key: value" lines or a ticked [template](history.md#pull-request-descriptions). `-` reads standard input.
- `--author` names who the human review of a ticked template is by: the pull request's author. For a pull request opened by a bot (a login ending in `[bot]`), the description must name a human on a line `Responsible person: @login`, and that person is the reviewer; a bot can't be.
- `--base` is the branch the pull request goes into. `HEAD^1` is the first parent of GitHub's merge preview, the base branch as this run merged it. A pull request into another branch than the default one declares nothing, so its description isn't applied or checked.

With `--declare-from`, `lint` checks the pull request as a whole, before it is merged (aisignoff >= 1.0.0rc3):

- **The description must be complete on its own:** all three levels, the names they need (the models for G1–G3, the reviewing model for A1–A3, the responsible person), the [built-in rules](levels.md#what-a-valid-declaration-needs) and the policy. A review of A2 or A3 gives its highest finding and its report, a link or a file that the pull request adds or modifies ([Severity](levels.md#severity)); any severity passes, since a finding is recorded, not a threshold. This holds also for a pull request with no lines to declare, such as one that changes only `SIGNOFF.toml`, which aisignoff never declares itself. (With `merge-method = "rebase"`, the description lands nowhere and isn't checked.)
- **The base branch sets the rules.** With `--base`, the `[policy]` of the base branch's `SIGNOFF.toml` applies to the merged result, not the pull request's own.
- **A pull request can't change them.** A change to `[policy]`, `exclude`, `[history]` or `version` in `SIGNOFF.toml`, or its removal, fails, and so does a change to the entries of `.git-blame-ignore-revs` (or the `ignore-revs-file`), which give lines to other commits. (`version` decides the scale the AI review levels are read on. A change to version 4 that leaves an entry's level as it was written fails also for a maintainer: [convert the file](migrating.md#to-signofftoml-version-4-the-ai-review-scale-of-100rc6).) Maintainers commit such changes to the default branch directly, or the workflow passes `--allow-policy-change` for pull requests it trusts (for example by their author's permission). Even then the pull request itself is checked under the base branch's `[policy]`, and `lint` says that it changes the rules: a change can't lower the bar for itself, and the new rules apply to the pull requests after it. (`exclude` and `[history]` are read from the pull request either way.) A repository's first `SIGNOFF.toml` is not a change.
- **Without `SIGNOFF.toml`,** only the description is checked, so the same workflow can check pull requests in repositories that declare no files.

`report --json` with the same options adds `pull_request`: the levels and names the description declares, whether it `applies` (not for a pull request into another branch) and its `errors`, for labels and the like.

These rules are for the check before the merge. How landed commits are read hasn't changed.

Pass the description through an environment variable as above, never by inserting `${{ … }}` into the script, which would let a description run shell commands.

## Merge, squash or rebase

How pull requests land decides which commit declares their lines ([table](history.md#merge-squash-or-rebase)). Two settings have to match:

- **On GitHub:** for merge and squash commits, *Settings → General → Pull Requests* → default commit message **Pull request title and description**. Without it, the description never reaches git, and the lines take the file-level declaration (or fail with `undeclared = "error"`).
- **In `SIGNOFF.toml`:** `merge-method = "merge"` (default), `"squash"` or `"rebase"` in `[history]`, so that checks before the merge show what will land.

With `rebase`, each commit lands as it is and must declare itself: the description check doesn't apply, and a pull request's merge preview is checked like the default branch.

## Merge queues

Add `merge_group:` to the workflow's triggers. A merge queue checks out the merge or squash commit that will be fast-forwarded onto the default branch, with its final message. On GitHub Actions, aisignoff recognises a queue's run by its ref (`gh-readonly-queue/…`) and checks `HEAD` as landed, as if it were already on the default branch; `lint` says so. This is the last check before the commit lands and needs no description: it catches a description that was left unfilled.

On other systems, pass `--landed` to `lint` (and to `report` and `badge`) in the queue's run.

## Release branches

Commits on a release or maintenance branch aren't on the default branch, so they never count as landed and fail nothing by default. Run `aisignoff lint --landed` (and `report --landed` for a release's report) on such a branch to hold it to the same rules: its own first-parent commits own their lines, and lines that came from the default branch, such as through a merge that brings the branch up to date, keep the levels they have there.

## Example workflows

Ready-to-copy files are in [`examples/`](https://github.com/industrial-mathematics-group/aisignoff/tree/main/examples); each explains itself in its header.

| File | What it does |
|---|---|
| [`signoff-lint.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-lint.yml) | `lint` on pushes, pull requests and merge queues; the folder tree in the job summary; the [folder report](report.md#the-interactive-report) as an artifact; the description check, commented out |
| [`signoff-badges.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-badges.yml) | the same check, plus [badges](report.md#badges) committed to a `badges` branch on pushes to `main` |
| [`signoff-pr-diff.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pr-diff.yml) | `aisignoff diff` of a pull request, with its description, in the job summary |
| [`signoff-pr-files.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pr-files.yml) | the declarations of the files a pull request changes, in the job summary and as annotations in *Files changed* |
| [`signoff-release.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-release.yml) | attaches the summary, `report --json` and the folder report to each GitHub release |
| [`signoff-pages.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pages.yml) | publishes the folder report to GitHub Pages (only for repositories without another Pages site) |
| [`signoff-request.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-request.yml) with the issue form [`ISSUE_TEMPLATE/signoff-request.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/ISSUE_TEMPLATE/signoff-request.yml) | turns an issue into a pull request that changes `SIGNOFF.toml` ([below](#signoff-requests-from-issues)) |
| [`signoff-assistant.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-assistant.yml) | the `@signoff` assistant: Claude turns a request in plain words into the form's answers, or asks for what is missing, and hands them to `signoff-request.yml` ([below](#the-signoff-assistant)) |
| [`pre-commit-config.yaml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/pre-commit-config.yaml) | runs `aisignoff lint` before each commit |

Pick **one** of `signoff-lint.yml` and `signoff-badges.yml`; the others add to either. The pull request workflows only read the repository and never fail on their own, so they also work for pull requests from forks. To adapt them:

- **Default branch:** change `branches: [main]` (and `refs/heads/main` in `signoff-badges.yml`) if yours is called differently.
- **Version:** `AISIGNOFF_VERSION` pins the release CI installs. Dependabot doesn't see it.
- **Badge weight:** `WEIGHT: lines` in `signoff-badges.yml` weights each file by its lines.

!!! tip "Industrial Mathematics Group"
    Repositories of the group use the organisation's ready-made **File-signoff**, **PR-signoff** and **Signoff-Badges** workflows (*Actions → New workflow*, section "By Industrial Mathematics Group") instead of the first two; setup is in the organisation's [SETUP.md](https://github.com/industrial-mathematics-group/.github/blob/main/SETUP.md). The other examples work next to them.

## Signoff requests from issues

For people who'd rather not edit TOML or use git, an issue form and a workflow turn plain answers into a pull request, without AI:

1. Copy [`examples/ISSUE_TEMPLATE/signoff-request.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/ISSUE_TEMPLATE/signoff-request.yml) to `.github/ISSUE_TEMPLATE/` and [`examples/workflows/signoff-request.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-request.yml) to `.github/workflows/`.
2. Allow it to open pull requests: *Settings → Actions → General → Workflow permissions* → **Allow GitHub Actions to create and approve pull requests** (or let it act as [your own app](#your-own-bot-account)).
3. Set `DISPATCH_WORKFLOWS` in the workflow to the file name of your lint workflow (`signoff-lint.yml` by default). It needs `workflow_dispatch:` among its triggers, which the examples have.

Someone with write access opens an issue with the form **Signoff: declare or attest files** and picks one of three things to record:

| Choice | Written with | Fields |
|---|---|---|
| Declare files | [`aisignoff annotate`](commands.md#annotate) | paths, all three levels and their names |
| Raise the review of files | [`aisignoff attest`](commands.md#attest) (needs `[history]`) | paths, the human and/or AI review |
| Correct a commit | a [`[[commits]]`](signoff-toml.md#commits) entry (needs `[history]`) | the commit, the levels to correct |

The workflow writes the change on the branch `signoff-request/issue-<n>` and opens a pull request. aisignoff validates it as on the command line: a declaration that is incomplete or below the [policy](levels.md#minimum-levels), a path that doesn't exist, or a change after which `lint` fails where it passed before is refused with a comment on the issue. Editing the issue runs it again and updates the pull request.

The pull request description comes from the repository's PR template (else the organisation's default from its `.github` repository, else "Key: value" lines): the change as a diff and `Closes #<n>` under the first heading, **G0** ticked, since the workflow is a deterministic tool, and `Responsible person: @<requester>`. The requester reviews *Files changed*, ticks their own review of the change and merges. That description declares the change to `SIGNOFF.toml`, not the files the change declares, which the form's answers do.

!!! note "Pull requests that change only SIGNOFF.toml"
    aisignoff never declares `SIGNOFF.toml` itself, so such a pull request has no lines to declare, but its description still declares the change: [`lint --declare-from`](#checking-the-pull-request-description) requires it to be complete, so the check stays red until the requester has ticked their review. That is the human signoff the workflow leaves to them.

Pull requests opened with the workflow's `GITHUB_TOKEN` start no other workflows (GitHub's rule against loops), apart from `workflow_dispatch`. That's why the workflow starts your lint workflow on the branch, so its check shows on the pull request; a check that runs on `pull_request_target` with `edited` runs once the requester edits the description.

### Your own bot account

By default the branch, commit and pull request come from `github-actions[bot]`. To use a GitHub App of your own instead, with its name and avatar:

1. Create a GitHub App (*Settings → Developer settings → GitHub Apps*, for an organisation under its settings) with no webhook and the repository permissions **Contents**, **Pull requests** and **Issues**: read and write. Install it on the repositories.
2. Store its App ID as the Actions variable `SIGNOFF_APP_ID` and a private key it generates as the secret `SIGNOFF_APP_PRIVATE_KEY` (on the repository, or once for the organisation).

The workflow then gets a token with [`actions/create-github-app-token`](https://github.com/actions/create-github-app-token) and acts as `<app>[bot]`. Its pull requests start your checks like anyone's, so nothing is dispatched by hand, and the repository setting for `GITHUB_TOKEN` to open pull requests isn't needed. Without the variable, it falls back to `GITHUB_TOKEN`. The form's text never reaches a shell: the workflow reads it from the event file and passes it to aisignoff as separate arguments, and runs no code of the repository.

### The @signoff assistant

For requests in plain words, the optional [`signoff-assistant.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-assistant.yml) lets people write `@signoff` in a new issue or a comment:

> @signoff I wrote results/convergence/ with Claude Opus 5.5, which also checked its work. I reran the study and read the important parts.

It sends the conversation, the repository's file list, `SIGNOFF.toml` and the recent commits to Claude through the [Claude API](https://platform.claude.com/docs), which fills in the form's answers. Before anything is handed on, the answers go through the form's checks and, on a scratch copy of the default branch, through `aisignoff annotate` or `attest` and `lint`. What fails goes back to Claude once; what is still missing or ambiguous becomes questions in a comment, answered with another `@signoff` comment. Complete answers go, written exactly as the form writes them, to `signoff-request.yml` (through `workflow_call`), which checks them again and opens the pull request as above. Claude only suggests: it never writes `SIGNOFF.toml`, pushes or ticks a review.

```
@signoff + plain words ──► Claude: the form's answers ──► form checks + aisignoff (scratch copy)
   ▲   comment: questions, or what fails      │ missing, ambiguous or refused    │ complete
   └──────────────────────────────────────────┘                                  ▼
                                   signoff-request.yml: aisignoff, lint ──► PR ──► requester reviews, ticks, merges
```

Setup, in addition to the [form's](#signoff-requests-from-issues):

1. Copy `signoff-assistant.yml` to `.github/workflows/`, next to `signoff-request.yml` (its `uses:` names that file).
2. Create an API key in the [Claude Console](https://platform.claude.com) (best in a workspace with a spend limit) and store it as the Actions secret `ANTHROPIC_API_KEY`, on the repository or for the organisation. Without it, `@signoff` gets a comment that points to the form, and nothing else changes.
3. Optional: change `MODEL` (default `claude-sonnet-5-5`) and `MODEL_NAME`, the name the pull request declares, together; `EFFORT` sets how hard the model thinks. A request costs a few cents with the default model, mostly for the file list it reads.

Because an AI turned the requester's words into the answers, the pull request ticks **G1** and the model instead of **G0**, with **A0** since no other AI session reviewed the answers (aisignoff checks them before the pull request opens), and says that the answers come from the assistant. The requester checks the diff and ticks their review as for the form; they can correct the ticks.

!!! warning "Prompt injection"
    Issue text is input from people, and the model reads it. The assistant therefore answers only people with write access and leaves out the text of anyone else; the model has no tools and can only fill in a fixed JSON schema ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)), whose values are checked and passed to aisignoff as separate arguments, never to a shell; its comments can't mention other people or carry the workflow's hidden markers; and the API key is only in the step that calls the model. The human review of the pull request remains the signoff.

## pre-commit

```yaml
repos:
  - repo: https://github.com/industrial-mathematics-group/aisignoff
    rev: v1.0.0rc9   # the same version as in your workflows
    hooks:
      - id: aisignoff-lint
```

The hook checks the whole repository, not only the staged files, because an annotation can change the declaration of files elsewhere. Keep `rev` at the version your workflows pin: an older hook rejects newer `SIGNOFF.toml` features.

## Other CI systems

Anything that runs Python works the same way: install aisignoff, check out the whole history, run `aisignoff lint`, and read the exit code. For your own checks, `aisignoff report --json` gives every file's declaration in a [stable format](compatibility.md).
