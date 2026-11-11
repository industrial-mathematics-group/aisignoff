# Example workflows

Ready-to-copy files for adding aisignoff to a repository are in [`examples/`](https://github.com/industrial-mathematics-group/aisignoff/tree/main/examples). Each one explains itself in its header comment.

| File | What it does | Copy to |
|---|---|---|
| [`signoff-lint.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-lint.yml) | Fails the check when a file has no valid declaration; writes the level mix per folder to the job summary and uploads the [folder report](report.md) | `.github/workflows/` |
| [`signoff-badges.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-badges.yml) | The same check, plus README badges published to a `badges` branch | `.github/workflows/` |
| [`signoff-pr-files.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pr-files.yml) | Shows the declarations of the files a pull request changes | `.github/workflows/` |
| [`signoff-release.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-release.yml) | Attaches the declarations of all files and the folder report to each GitHub release | `.github/workflows/` |
| [`signoff-pages.yml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/workflows/signoff-pages.yml) | Publishes the folder report to GitHub Pages (only for repositories without another Pages site) | `.github/workflows/` |
| [`pre-commit-config.yaml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/pre-commit-config.yaml) | Runs `aisignoff lint` before each commit | `.pre-commit-config.yaml` |

Pick **one** of `signoff-lint.yml` and `signoff-badges.yml`; the others add to either.

!!! tip "Industrial Mathematics Group"
    Repositories of the group use the organisation's ready-made **File-signoff**, **PR-signoff** and **Signoff-Badges** workflows instead of the first two (*Actions → New workflow*, section "By Industrial Mathematics Group"); see [CI and badges](ci.md). `signoff-pr-files.yml`, `signoff-release.yml` and the pre-commit hook work next to them.

## Quick setup

Starting from a repository without declarations:

```bash
pipx install aisignoff
aisignoff init -g G0 -H H2 -a A0 --reviewed-by "Jane Doe"   # your default, see Getting started
aisignoff lint                                               # fix what it lists, with aisignoff annotate

mkdir -p .github/workflows
curl -sSfL -o .github/workflows/signoff.yml \
  https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/main/examples/workflows/signoff-lint.yml
git add SIGNOFF.toml .github/workflows/signoff.yml
```

The new workflow file is a file like any other, so `SIGNOFF.toml` must declare it too: the default for `**` usually does.

Then, in *Settings → Branches*, require the check `aisignoff / lint` on the default branch, so no undeclared file gets merged.

## Things to adjust

- **Default branch.** The examples run on pushes to `main`. Change `branches: [main]` (and `refs/heads/main` in `signoff-badges.yml`) if yours is called differently.
- **Version.** `AISIGNOFF_VERSION` pins the release that CI installs, so a new version can't fail your checks unannounced. Raise it when you update aisignoff locally. Dependabot doesn't see this pin.
- **Stricter lint.** `aisignoff lint --strict` also fails on annotations in `SIGNOFF.toml` that match no file, e.g. after a file was renamed.
- **Badge weight.** In `signoff-badges.yml`, `WEIGHT: lines` weights each file by its number of lines instead of counting files.

## The workflows

### Check (`signoff-lint.yml`)

Runs `aisignoff lint` on every push to `main` and every pull request, and adds the level mix of each folder (`aisignoff report --tree --markdown`) to the job summary of the run. The interactive [folder report](report.md) is uploaded as the artifact `aisignoff-report` of the run. The check fails when a file has no valid declaration or falls below the [policy](signoff-toml.md#minimum-levels).

### Check and badges (`signoff-badges.yml`)

The check above, plus a second job on pushes to `main`. It writes the three badge files with [`aisignoff badge`](commands.md#badge) and commits them to the branch `badges`, which it creates on its first run. The badges also update when the check fails, showing the undeclared share in red. Add them to the README as in [Badges](ci.md#badges).

raw.githubusercontent.com only serves files of public repositories, so the badges need a public repository.

### Changed files of a pull request (`signoff-pr-files.yml`)

For reviewers: which levels do the files this pull request touches declare?

- A table of the changed files, their levels and where each level comes from goes to the job summary.
- Each changed file gets an annotation with its levels in the *Files changed* tab. Files without a valid declaration are marked as errors.
- When the pull request doesn't change `SIGNOFF.toml`, a note reminds the author to update it if the changes were made or reviewed differently.

It only reads the repository, so it works for pull requests from forks too. It never fails on its own; that is the job of the check.

### Release report (`signoff-release.yml`)

When a release is published, it adds `aisignoff-report.txt` (the summary and the folder tree), `aisignoff-report.json` (every file, from [`aisignoff report --json`](commands.md#report)) and `aisignoff-report.html` (the [folder report](report.md)) to the release, describing the code at its tag. It warns, but still uploads, when files are undeclared.

### Folder report on Pages (`signoff-pages.yml`)

Publishes the [folder report](report.md) to GitHub Pages on every push to `main`. Needs *Settings → Pages → Build and deployment → Source: GitHub Actions*. A repository has a single Pages site, so use it only when Pages isn't used for anything else; a repository with a documentation site writes the report into that site instead ([Publishing the report](report.md#publishing-the-report)).

### pre-commit hook

aisignoff provides a hook for [pre-commit](https://pre-commit.com), so undeclared files are caught before they are committed:

```yaml
repos:
  - repo: https://github.com/industrial-mathematics-group/aisignoff
    rev: v0.5.0   # the hook exists from the first release after v0.4.2
    hooks:
      - id: aisignoff-lint
```

It checks the whole repository, not just the staged files, because a declaration in `SIGNOFF.toml` can change the levels of files elsewhere. For releases up to v0.4.2, [`pre-commit-config.yaml`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/pre-commit-config.yaml) shows a `repo: local` hook that installs aisignoff from PyPI.
