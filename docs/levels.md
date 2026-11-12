# Levels and rules

The levels come from the [AI policy](https://github.com/industrial-mathematics-group/.github/blob/main/.github/CONTRIBUTING.md#ai-assisted-contributions) of the Industrial Mathematics Group. A declaration gives one level per axis, plus the names behind it.

## The three axes

| Axis | Key | Levels | Names key |
|---|---|---|---|
| Generation | `AI-Generation` | **G0** Human · **G1** AI-assisted · **G2** AI-generated · **G3** AI-autonomous | `Assisted-by`: the AI tools and models that wrote it |
| Human review | `Human-Review` | **H0** Plausibility check · **H1** Tested · **H2** Reviewed line by line · **H3** Independently validated | `Reviewed-by`: the responsible human |
| AI review | `AI-Review` | **A0** None · **A1** Self-check by the generating session · **A2** Review by a new session · **A3** Extensive review or benchmark by a different model | `AI-Reviewed-by`: the reviewing model, and how |

The levels on each axis build on each other. For generation, declare the highest level of any substantial part.

## What a valid declaration needs

| Key | Needed |
|---|---|
| `AI-Generation`, `Human-Review`, `AI-Review` | always |
| `Reviewed-by` | always (every level of human review has a responsible person) |
| `Assisted-by` | for G1–G3; not allowed with G0 |
| `AI-Reviewed-by` | for A1–A3; not allowed with A0 |

Two rules always apply:

- **AI-written content must be checked:** G1–G3 need at least A1.
- **Human-written content has no self-check:** G0 can't be A1, since there is no generating session. Any AI review of human-written content is A2 or A3.

## Minimum levels

A repository can require more with a `[policy]` table in `SIGNOFF.toml`:

```toml
[policy]
"*" = { human = "H1" }               # every file
G3  = { human = "H2", ai = "A2" }    # AI-autonomous content needs more
```

- `"*"` is the default for every generation level; `G0`–`G3` override it key by key.
- `human` takes H0–H3, `ai` takes A0–A3.
- The built-in A1 minimum for G1–G3 always applies on top. For G0, a minimum of `ai = "A1"` means A2.

`lint` fails on any file or line below the policy.

## TODO: left for a person

Any level or name may be `TODO`. An AI agent that declares its own work can leave the human review to the person who will do it:

```bash
aisignoff annotate src/solver.py -g G3 -H TODO -a A1 \
    --assisted-by "Claude Opus 5.5 (Anthropic)" \
    --ai-reviewed-by "Claude Opus 5.5 (Anthropic), self-check by the generating session"
```

`-H TODO` without `--reviewed-by` writes `Reviewed-by` as `TODO` too. The axes that are filled in are still checked, and `lint` fails until every `TODO` is replaced.

## How reports count an axis

[Reports](report.md) and badges count each axis on its own. An axis is *undeclared* when its level is missing, `TODO` or invalid, or when an error is about that axis (a missing name, a level below the policy). An error about one axis leaves the other two as declared.
