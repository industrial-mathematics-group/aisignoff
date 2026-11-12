# Snapshots

Without a snapshot, aisignoff works out every line's levels from the whole history on every run. A changed annotation, a new `[[commits]]` entry or a new version of aisignoff could then change the levels of code that landed long ago. A snapshot fixes them.

## Taking a snapshot

```bash
git switch --detach origin/main     # a commit of the default branch, nothing else changed
aisignoff freeze --prune
git switch -c freeze
git add SIGNOFF.snapshot.json SIGNOFF.toml && git commit -m "Freeze the declarations"
```

`aisignoff freeze` writes `SIGNOFF.snapshot.json` next to `SIGNOFF.toml`: the levels and names of every line as of the checked-out commit. It refuses unless:

- `[history]` is enabled and the whole history is there;
- `HEAD` is a commit of the default branch and the working tree is clean;
- `lint` passes there without errors, and without warnings, since a snapshot would keep the levels a warning is about for good. `--allow-warnings` freezes despite warnings.

Commit the file, through a pull request if you use them.

## What a snapshot does

- **A line that doesn't change keeps the snapshot's levels,** whatever a later version, a changed annotation or a new `[[commits]]` entry would say. That includes lines that took the file-level declaration: editing the annotation or the inline tags afterwards doesn't change them. A line follows its file through a rename. A file whose content is again exactly what the snapshot recorded, such as after a revert, gets the snapshot's levels back.
- **Lines that change afterwards** are declared by the commits that land them, as in [Declaring lines](history.md). History is only read from the snapshot's commit on, which also makes `lint` faster.
- **A frozen line changes only through an attestation,** which can raise its reviews, or through `freeze --reset` (below). Its generation stays.
- **Files the snapshot doesn't have**, because they were excluded or declared with `precedence = "override"` when it was taken, are resolved from history once they're included.

Take a new snapshot whenever you like, for example at each release. It replaces the old one, carries over the lines that haven't changed, and adds the lines that landed since.

## Pruning: `freeze --prune`

Every `[[commits]]` and `[[attestations]]` entry in `SIGNOFF.toml` at freeze time has its effect recorded in the snapshot. `--prune` moves these entries out of `SIGNOFF.toml` (with the comment lines directly above them) into an `archive` list in the snapshot, one item per freeze. `SIGNOFF.toml` then starts afresh after each freeze.

The archived entries still count wherever levels are worked out from history: for files the snapshot doesn't have, files worked out again with `--reset`, and files whose content doesn't match the snapshot. Commit both files together.

## Working files out again: `freeze --reset`

```bash
aisignoff freeze --reset src/solver.py docs/index.md
```

`--reset FILE...` works these files out from history again, with the `[[commits]]` entries of `SIGNOFF.toml` and of the archive, the attestations, and the annotations and inline tags as they are now, instead of keeping their frozen levels. Use it to correct a frozen generation with a `[[commits]]` entry, or to apply a changed annotation to frozen lines. The snapshot lists these files under `reset`, so its check works them out the same way.

Correcting a frozen generation takes two steps, since `freeze` runs on a commit of the default branch:

1. Land the `[[commits]]` entry on the default branch. On its own it changes no frozen line, and `lint` notes that it is for a commit from before the snapshot.
2. Run `aisignoff freeze --reset FILE` on that commit and land the new snapshot.

`--reset` works out *every* line of the file with today's rules, not only the corrected commit's. Frozen levels that no current rule gives, such as levels kept from an older version of aisignoff, are replaced too.

## How a snapshot is checked

The snapshot is generated, never edited by hand. When `SIGNOFF.snapshot.json` differs from the default branch's copy, or a commit being checked changed it (`HEAD`'s commit, or on GitHub Actions every commit of the push), `lint` checks it by working it out again: it checks out the snapshot's commit in a temporary worktree (with git hooks off), computes what `freeze` would write there (from the snapshot before it, that commit's `SIGNOFF.toml` and the snapshot's `reset` files), and fails if any line's levels or names, or the archive, differ. `aisignoff freeze --check` runs the same check on its own. A snapshot that can't be checked, such as one whose commit isn't there, fails too.

This holds whatever version wrote the snapshot: a snapshot written by another version of aisignoff that works levels out differently fails, and the message names both versions. Write the snapshot with the version your CI uses. git runs with the settings that change its results pinned, so a personal git config (an ignore-revs file of your own, another diff algorithm) doesn't change the levels.

A snapshot only moves forward. `lint` also fails when the changed snapshot is of an older commit than the default branch's, or drops archived entries of the default branch's snapshot, which are recorded nowhere else: by putting back an older snapshot, deleting it, or taking one afresh. To take one afresh, put the archived entries back into `SIGNOFF.toml` first. `freeze --prune` writes each archived commit with its full hash, so it can't become ambiguous later.

`lint` also fails when a file's blob or number of lines doesn't match the snapshot's commit. Such a file is resolved from history until the snapshot is restored or written again.

## The file

The snapshot has one line per distinct declaration and one per file, so a new snapshot is a readable diff:

```json
{
 "format": 1,
 "aisignoff": "0.14.0",
 "commit": "f4d6052e6d7ff657fac433bfec90d22689c7130f",
 "declarations": [
  {"AI-Generation": "G0", "Human-Review": "H2", "AI-Review": "A0", "Assisted-by": [], "AI-Reviewed-by": [], "Reviewed-by": ["Jane Doe"], "source": "SIGNOFF.toml [1]"},
  {"AI-Generation": "G3", "Human-Review": "H1", "AI-Review": "A1", "Assisted-by": ["Claude Opus (Anthropic)"], "AI-Reviewed-by": ["Claude Opus (Anthropic), self-check by the generating session"], "Reviewed-by": ["Jane Doe"], "source": "commit d307518 (Add solver part (#1)), pull request checkboxes"}
 ],
 "files": {
  "src/solver.py": {"blob": "…", "runs": [[1, 20, 0], [21, 30, 1]]}
 }
}
```

A run is `[first line, last line, index into declarations]`. Optional keys are `reset` (files worked out again) and `archive` (pruned entries).
