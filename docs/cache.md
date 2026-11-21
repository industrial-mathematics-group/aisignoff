# The blame cache

With `[history]`, aisignoff works out every line from the whole history on every run: the commit that landed it (`git blame --first-parent`), and where needed the commit that wrote it. On a long history that is most of the time a run takes, so aisignoff keeps what `git blame` found in a cache, and the next run only blames the commits since.

| Repository | Commits | Lines | Without the cache | With it, after the default branch moved on | With it, at the same commit |
|---|---|---|---|---|---|
| pytest | 17,928 | 186k | 14.7 s | 5.3 s (200 commits) | 3.0 s |
| Django | 35,130 | 1.1M | 7.7 min | 17 s (300 commits) | 6.6 s |

Measured with aisignoff 0.17.0 on 4 cores; the results with and without the cache were the same for every line.

## What it holds

The cache is in the repository's git folder, `.git/aisignoff/`, one file per commit of the default branch (the newest three are kept). For each line of each file it holds the commit `git blame` gives it, with the line's number and path there, for each merge commit the commits it brought in, and for each binary or empty file and symlink the commit that last changed it. These are facts about the history alone, never levels: a changed `SIGNOFF.toml`, a new attestation or a new review counts on the next run as it would without the cache.

A run uses the newest cached commit on the default branch's first-parent history. `git blame` then stops there, and a line from before it is what blame found at that commit: blame passes a line that a commit didn't change on to the commit's parent, so what comes after doesn't change where it ends up. A file the cache doesn't have, or a line it can't place, is blamed over the whole history as without it.

The cache is only used with the same blame options it was written with: `[history]` `ignore-whitespace` and the commits of the ignore-revs file. With others, or when its file can't be read, the run doesn't use it. It is never committed, needs no check, and deleting it only makes the next run slower. Set `AISIGNOFF_NO_CACHE=1` to turn it off.

## In CI

A CI run starts from a fresh checkout, so it has no cache unless the workflow keeps it. With GitHub Actions, restore it before `aisignoff lint` and save it after:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/cache@v4
        with:
          path: .git/aisignoff
          key: aisignoff-${{ github.sha }}
          restore-keys: aisignoff-
      - run: pip install "aisignoff==0.20.0"
      - run: aisignoff lint
```

`restore-keys` restores the newest cache of an earlier run, the run blames the commits since, and the cache under the new key is saved for the next one. A cache from history that was rewritten, or of another branch, has no commit on this one's history and is not used. A cache written in an earlier format is not used either: the first run of a release that changes the format blames the whole history once and saves the cache again, so an upgrade needs no step.

## Snapshots (up to 0.16)

Up to 0.16, `aisignoff freeze` wrote `SIGNOFF.snapshot.json` with the levels of every line, and lines that didn't change kept them. A snapshot stored levels, not where they came from, so a review recorded after it could miss its lines or be counted twice, and it took a check of its own. 0.17 reads every line from the history again and keeps only the cache. To move a repository off its snapshot, see [Upgrading](migrating.md#to-017-no-snapshots).
