# CI and badges

## GitHub Actions

Add `.github/workflows/signoff.yml` to check every push and pull request:

```yaml
name: File-signoff

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install aisignoff
      - run: aisignoff lint
```

Then require the check in the branch protection of `main`, so no file goes undeclared. With [line-by-line declarations](history.md), check out the whole history: `actions/checkout` with `fetch-depth: 0`. That also fetches the default branch, which aisignoff needs to tell which lines have landed. In a pull request, the lines it adds fail nothing on their own, since its description declares them when it lands; `aisignoff lint --declare-from` checks the description before the merge ([Lines that haven't landed yet](history.md#lines-that-havent-landed-yet)).

With a **merge queue**, add `merge_group:` to the workflow's triggers. The queue's run checks out the commit that will land, and `lint` checks it as landed: this is the run that catches a description that was left unfilled. On a **release branch**, or a tag cut from one, run `aisignoff lint --landed` and `aisignoff report --landed`, since commits that aren't on the default branch fail nothing otherwise and show only what they claim themselves.

More complete versions, with badges, a summary of the files a pull request changes, release reports and a pre-commit hook, are in [Example workflows](integration.md).

!!! tip "Industrial Mathematics Group"
    Repositories of the group don't need to write this themselves. Add the ready-made **File-signoff** workflow (*Actions → New workflow*, section "By Industrial Mathematics Group"). It runs `aisignoff lint` and publishes the badges to the `badges` branch. Setup details are in the organisation's [SETUP.md](https://github.com/industrial-mathematics-group/.github/blob/main/SETUP.md).

## Badges

`aisignoff badge` writes three [shields.io endpoint](https://shields.io/badges/endpoint-badge) files, one per axis, e.g. `G0 60% · G2 30% · G3 10%`. The badges turn red and show an "undeclared" share while files are missing a valid declaration.

Publish the files somewhere public, such as a `badges` branch, and link them from the README:

```markdown
![AI generation](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<owner>/<repo>/badges/aisignoff-generation.json)
![Human review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<owner>/<repo>/badges/aisignoff-human-review.json)
![AI review](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<owner>/<repo>/badges/aisignoff-ai-review.json)
```

For the detail behind the badges, which folders and files make up each share, see the [folder report](report.md). The badges can link to it instead of to the levels.

## Other tools

Anything that runs Python works the same way: install aisignoff and run `aisignoff lint`. It exits with `1` when declarations are missing or invalid, and `2` on configuration errors. `aisignoff report --json` gives the declarations of all files for your own checks, and `aisignoff report --html` an interactive [folder report](report.md).
