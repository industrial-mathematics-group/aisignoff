# Evidence for the review of aisignoff 0.22.0 (Claude Fable)

The probes of [the report](../2026-11-25-v0.22.0-fable.md). Each one drives the `aisignoff` command line on throwaway git repositories, as a workflow does, and imports nothing from the package. They ran on Linux with git 2.47.3 and Python 3.13.5 against commit `e0388d5` (0.22.0), and where the report says so also against the sources of the tag `v0.20.1`.

Run one with the executable under test and a scratch folder, which it fills and overwrites:

```bash
python fuzz_binary_text.py /path/to/venv/bin/aisignoff /tmp/scratch 300
python probe_keys.py /path/to/venv/bin/aisignoff /tmp/scratch
```

The probes set `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` to `/dev/null` and `AISIGNOFF_NO_CACHE=1` for themselves (`lib.py`), so the machine's git configuration and the blame cache play no part unless a probe turns them on.

| File | What it checks | Recorded output |
|---|---|---|
| `lib.py` | the helper: a scratch repository, commits, the command line | |
| `fuzz_binary_text.py` | contract 5.6 and 5.7 (D6): for 300 random cases (old side text, binary to git, or binary only to aisignoff's 16 KiB probe; `.gitattributes`; renames; both settings of `ignore-whitespace`), the levels of every line before the merge, after the merge, and after the merge with the blame cache on are the same, and `diff` counts what lands | `fuzz_binary_text-results.txt`: 0 of 300 failed |
| `probe_units.py`, `ptr_filter.py` | units at the edges of 0.21.0 and 0.22.0: the counts of `diff` and of `report --html --since` for a replaced binary file (finding 2), files that git converts before and after the merge (finding 1) | `probe_units-results.txt`, and `probe_units-results-0.20.1.txt` for the sources of v0.20.1 |
| `probe_keys.py` | contract 4.2.3 and 4.4.2: an unknown key in every table and in record files, `requires-aisignoff`, the pull request that removes an unknown key (finding 3), and 320 values of the wrong type (no internal error) | `probe_keys-results.txt` |
| `probe_gitconfig.py` | contract 2.1 and 2.2: 27 user-level git settings and 6 environment variables, one at a time, before and after the merge (finding 4) | `probe_gitconfig-results.txt`, and `probe_gitconfig-results-0.20.1.txt` (only the differences) |
| `probe_grammar.py` | contract 4.3 and "The exact form": boxes, key lines, fences, comments, the findings line (finding 5) | `probe_grammar-results.txt` |
| `probe_exit.py` | contract 2.3 and 6.2: git too old or missing, settings that name nothing, files that can't be read or written, a repository git can't read (findings 6, 8 and 9) | `probe_exit-results.txt`, and `probe_exit-results-0.20.1-excerpt.txt` for the two older problems |
| | the test suite, `lint --strict`, and the validation of the record file | `commands-results.txt` |

In the recorded output of `probe_exit.py`, `DIFF` marks a result other than the contract's, and `ok` one that matches it.

The runs against v0.20.1 used a worktree of the tag with `PYTHONPATH` set to its `src`, in the environment of 0.22.0. `--version` therefore still says 0.22.0 there; the code is the tag's.
