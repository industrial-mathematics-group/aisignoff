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
      - run: pip install "aisignoff==1.0.0rc2"
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
- `--author` names who the human review of a ticked template is by.
- `--base` is the branch the pull request goes into. `HEAD^1` is the first parent of GitHub's merge preview, the base branch as this run merged it. A pull request into another branch than the default one declares nothing, so its description isn't applied or checked.

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
| [`pre-commit-config.yaml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/pre-commit-config.yaml) | runs `aisignoff lint` before each commit |

Pick **one** of `signoff-lint.yml` and `signoff-badges.yml`; the others add to either. The pull request workflows only read the repository and never fail on their own, so they also work for pull requests from forks. To adapt them:

- **Default branch:** change `branches: [main]` (and `refs/heads/main` in `signoff-badges.yml`) if yours is called differently.
- **Version:** `AISIGNOFF_VERSION` pins the release CI installs. Dependabot doesn't see it.
- **Badge weight:** `WEIGHT: lines` in `signoff-badges.yml` weights each file by its lines.

!!! tip "Industrial Mathematics Group"
    Repositories of the group use the organisation's ready-made **File-signoff**, **PR-signoff** and **Signoff-Badges** workflows (*Actions → New workflow*, section "By Industrial Mathematics Group") instead of the first two; setup is in the organisation's [SETUP.md](https://github.com/industrial-mathematics-group/.github/blob/main/SETUP.md). The other examples work next to them.

## pre-commit

```yaml
repos:
  - repo: https://github.com/industrial-mathematics-group/aisignoff
    rev: v1.0.0rc2   # the same version as in your workflows
    hooks:
      - id: aisignoff-lint
```

The hook checks the whole repository, not only the staged files, because an annotation can change the declaration of files elsewhere. Keep `rev` at the version your workflows pin: an older hook rejects newer `SIGNOFF.toml` features.

## Other CI systems

Anything that runs Python works the same way: install aisignoff, check out the whole history, run `aisignoff lint`, and read the exit code. For your own checks, `aisignoff report --json` gives every file's declaration in a [stable format](compatibility.md).
