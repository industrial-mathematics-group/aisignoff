# Quick start

## Install

```bash
pipx install aisignoff        # or: uv tool install aisignoff, or: pip install aisignoff
```

aisignoff needs Python 3.11 or newer and git, and has no other dependencies. For the development version: `pipx install "git+https://github.com/industrial-mathematics-group/aisignoff"`.

## 1. Declare the files

In the repository root, set a default for everything. Here: written by a human, reviewed line by line, no AI review.

```bash
aisignoff init -g G0 -H H2 -a A0 --reviewed-by "Jane Doe"
```

This creates a commented [`SIGNOFF.toml`](files.md) with one annotation for `**`. Then declare what is different, by file, folder or quoted glob. The last matching annotation wins:

```bash
aisignoff annotate results/ -g G2 -H H1 -a A1 \
    --assisted-by "Claude Opus 5.5 (Anthropic)" \
    --ai-reviewed-by "Claude Opus 5.5 (Anthropic), self-check by the generating session" \
    --reviewed-by "Jane Doe"
```

Check the result:

```bash
aisignoff lint            # fails if any file lacks a valid declaration
aisignoff report --files  # one line per file, with where its levels come from
```

For what the levels mean and what each one requires, see [Levels and rules](levels.md).

## 2. Check it in CI

Add a workflow that runs `aisignoff lint` on every push and pull request, and require it in the branch protection of the default branch:

```bash
mkdir -p .github/workflows
curl -sSfL -o .github/workflows/signoff.yml \
  https://raw.githubusercontent.com/industrial-mathematics-group/aisignoff/main/examples/workflows/signoff-lint.yml
```

The workflow file needs a declaration like any other file; the default for `**` usually covers it. More on this in [CI and workflows](ci.md).

## 3. Declare lines from pull requests (optional)

When code is developed through pull requests, let each pull request declare the lines it changes:

1. Add `[history]` to `SIGNOFF.toml`:

    ```toml
    [history]
    enabled = true
    merge-method = "squash"   # or "merge" (the default) or "rebase": how your pull requests land
    ```

2. In *Settings → General → Pull Requests*, set the default commit message for merge and squash commits to **Pull request title and description**, so the description lands in git.
3. Declare the levels in each pull request description, as "Key: value" lines or with the checkboxes of a pull request template:

    ```
    AI-Generation: G3
    Assisted-by: Claude Opus 5.5 (Anthropic)
    Human-Review: H1
    Reviewed-by: Jane Doe
    AI-Review: A1
    AI-Reviewed-by: Claude Opus 5.5 (Anthropic), self-check by the generating session
    ```

4. Check out the whole history in CI (`fetch-depth: 0`), and add the [description check](ci.md#checking-the-pull-request-description) so an incomplete description fails before the merge.

Existing lines keep the file-level declarations until they change. When everything passes, record the result with a [snapshot](snapshots.md) so it stays as it is. The full model is in [Declaring lines](history.md).
