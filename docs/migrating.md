# Migrating

`aisignoff migrate` handles both the rename from aidecl and older versions of the file format. It converts `SIGNOFF.toml` and the inline tags all or nothing. Run it with `--dry-run` first to see what would change.

## From 0.11 with `[history]`

Only for repositories with `[history]` in `SIGNOFF.toml`. Version 0.12 decides a line's levels by simpler rules: [one owner per line](history.md#where-a-lines-levels-come-from). A review that a commit inside a pull request declared, or a pull request merged into another one, no longer counts, so some lines of existing code would report other levels after the upgrade.

To keep what 0.11 reported, take a snapshot with 0.11 before upgrading. [`freeze-from-0.11.py`](https://github.com/industrial-mathematics-group/aisignoff/blob/main/examples/freeze-from-0.11.py) writes one in the format of [`aisignoff freeze`](history.md#freezing-the-levels-aisignoff-freeze):

```bash
git switch --detach origin/main     # a commit of the default branch, nothing else changed
uv run --no-project --with aisignoff==0.11.0 python freeze-from-0.11.py
git switch -c freeze && git add SIGNOFF.snapshot.json && git commit -m "Freeze the declarations of 0.11"
```

Then upgrade. Lines that don't change keep those levels, and the new rules apply to what lands afterwards. Without the snapshot, run `aisignoff lint` after upgrading and check `aisignoff report`:

- `[[commits]]` entries that gave a review to a commit inside a pull request are reported. Move them to the merge commit, or attest the file.
- A pull request template that was merged without a ticked generation or human review box is now a `TODO`, not the file-level declaration. Declare that commit with a `[[commits]]` entry.
- `lint` no longer fails on a feature branch for what a commit leaves to its pull request, and the workflow that shows a pull request's lines is shorter: copy the new [`signoff-pr-diff.yml`](integration.md).

## From aidecl

aidecl (up to version 0.3.0) was renamed to aisignoff. The command is now `aisignoff`, and `AIDECL.toml` is now `SIGNOFF.toml`. Keys, levels and inline tags are the same.

1. **Reinstall:** `pipx uninstall aidecl && pipx install aisignoff`.
2. **Rename the file:** `aisignoff migrate` renames `AIDECL.toml` to `SIGNOFF.toml` and keeps its content. If it still uses format version 1 or 2, it's converted in the same step. Commit both sides of the rename: `git add -A SIGNOFF.toml AIDECL.toml`.
3. **Update the badges:** they're now called `aisignoff-generation.json`, `aisignoff-human-review.json` and `aisignoff-ai-review.json` (see [Badges](ci.md#badges)).

Until you migrate, aisignoff still reads `AIDECL.toml` and prints a warning. Having both files is an error.

## From format version 2

Version 2 had the AI review scale A-, A0–A3. The scale moved up by one, so only `AI-Review` (and `ai` in `[policy]`) changes. Comments and layout of `SIGNOFF.toml` are kept.

| Old | New |
|---|---|
| A- (none) | A0 |
| A0 (self-check) | A1; for G0 a TODO, since human-written content has no self-check |
| A1 (independent session) | A2 |
| A2 (different model) | A2, with a note: raise it to A3 if the review was extensive or benchmarked |
| A3 (different model with benchmark) | A3 |

**Repositories with inline tags only:** without `SIGNOFF.toml`, aisignoff can't tell which scale the inline tags use. Run `aisignoff migrate --from 2`; `migrate` points this out when it finds `AI-Review: A-`. It converts the tags and creates a version-3 `SIGNOFF.toml` without annotations. That file records that the tags are converted, so they're never shifted twice. Once `SIGNOFF.toml` is version 3, `--from 2` is refused.

## From format version 1

Version 1 had one verification axis, V0–V3:

| Old | New |
|---|---|
| V0 (human, line by line) | H2, and A0 for G0 |
| V1 / V2 (independent agent, same / different model) | A2 |
| V3 (human + independent agent) | H2 + A2 |
| `Tested-by` | `Reviewed-by` |
| `Verified-by` | `AI-Reviewed-by` |

Comments in `SIGNOFF.toml` are not carried over from version 1.

## TODOs after migrating

What the old levels don't say must be added by a person. Examples are the human review of a V1 file, or the AI review of an AI-written V0 file. `migrate` marks these with a `TODO` comment in `SIGNOFF.toml` and with a `TODO` value in inline tags (e.g. `# Human-Review: TODO`). `lint` reports them until they're filled in.
