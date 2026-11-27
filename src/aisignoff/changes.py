"""The declarations of the changes that landed: one per commit of the default branch's first-parent history
(a merged pull request's merge or squash commit), read from its message as the check before the merge reads
a pull request description. `aisignoff badge --commits` counts them, for repositories that declare changes
but not files (no SIGNOFF.toml needed).

Where the repository has a SIGNOFF.toml, its scale counts (version 3: the AI review scale before version 4,
taken over to today's) and so do its [[commits]] corrections. A level that contradicts the definitions is
counted as what it is: an AI review whose reviewer is only a self-check is A0, and an A2 or A3 by only a model
that wrote the change is A1 (a new session of it). An axis with conflicting levels in one message is unknown."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .config import load
from .history import _git, _prose_lines, _records, check_git, parse_message, pieces_from_values, short
from .model import AI, GENERATION, HUMAN, LEVEL_KEYS, TODO, _same_model, error_axes, mentions_self_check

FORMAT = "%H%x00%P%x00%s%x00%an <%ae>%x00%B%x00"
UNKNOWN = "unknown"

# The first version of the policy declared "AI-Verification: V0-V3" instead of human and AI review. Commit
# messages can't be rewritten, so those commits keep counting, mapped conservatively: what V0-V3 can't tell
# is unknown.
_VERIFICATION = re.compile(r"^AI-Verification:[ \t]*(V[0-3])[ \t]*$", re.I)
_V_HUMAN = {"V0": "H2", "V3": "H2"}
_V_AI = {"V1": "A2", "V2": "A2", "V3": "A2"}


@dataclass
class Changes:
    """How many of the commits declare which level, per axis."""

    commits: int = 0
    generation: Counter = field(default_factory=Counter)
    human: Counter = field(default_factory=Counter)
    ai: Counter = field(default_factory=Counter)
    boxes: int = 0  # declared with the ticked boxes of the pull request template
    legacy: int = 0  # declared with the V0-V3 trailers of the first policy
    corrected: int = 0  # with a [[commits]] entry of SIGNOFF.toml
    lowered: int = 0  # an AI review that the definitions make lower (a self-check: A0; the writing model: A1)
    conflicting: int = 0  # an axis with conflicting levels, counted as unknown
    version_3: bool = False  # SIGNOFF.toml says version 3: the AI review scale before version 4
    problems: list[str] = field(default_factory=list)

    @property
    def declared(self) -> int:
        return sum(self.generation.values())

    @property
    def trailers(self) -> int:
        return self.declared - self.boxes - self.legacy


def _verification(body: str) -> str | None:
    for line in _prose_lines(body):
        m = _VERIFICATION.match(line)
        if m:
            return m.group(1).upper()
    return None


def _level(piece, levels: dict) -> str:
    """A piece's level as counted: unknown where it is missing, left TODO or not a level."""
    if piece is None or piece.level in (None, TODO):
        return UNKNOWN
    level = str(piece.level).upper()
    return level if level in levels else UNKNOWN


def _corrections(root: Path, config) -> dict[str, dict]:
    """Commit -> the axes its [[commits]] entries of SIGNOFF.toml correct (entries that name no commit of
    this repository are lint's to report)."""
    out: dict[str, dict] = {}
    for entry in config.commits:
        sha = (_git(root, "rev-parse", "--verify", "--quiet", f"{entry.commit}^{{commit}}", check=False) or "").strip()
        if sha:
            out.setdefault(sha, {}).update(
                pieces_from_values(entry.values, f"{entry.filename} [[commits]] {short(sha)}", "commit"))
    return out


def _ai_as_defined(level: str, piece, assisted_by) -> str:
    """An AI review as the definitions count it: a reviewer that is only a self-check is no review (A0), and
    a different-model level by only a model that wrote the change is a new session of it (A1)."""
    reviewers = [n for n in (piece.names if piece is not None else ()) if n != TODO]
    if level in ("A1", "A2", "A3") and reviewers and all(mentions_self_check(n) for n in reviewers):
        return "A0"
    if level in ("A2", "A3") and reviewers and all(_same_model(n, assisted_by) for n in reviewers):
        return "A1"
    return level


def count(root: Path, rev: str = "HEAD") -> Changes:
    """The declarations of the commits on the first-parent history of `rev`. Commits without a generation
    level (from before the policy) are not counted."""
    check_git()
    config = load(root)  # no SIGNOFF.toml: today's scale, no corrections
    out = Changes(version_3=config.version_3)
    corrections = _corrections(root, config)
    log = _git(root, "log", "--first-parent", f"--format={FORMAT}", rev)
    for sha, _parents, _subject, author, message in _records(log or ""):
        out.commits += 1
        body = message.split("\n", 1)[1] if "\n" in message else ""
        pieces, both = parse_message(body, author, f"commit {short(sha)}", config.version_3, landed=True)
        if sha in corrections:
            pieces = {**pieces, **corrections[sha]}
        g = _level(pieces.get(0), GENERATION)
        if g == UNKNOWN:
            continue
        if sha in corrections:
            out.corrected += 1
        if both:
            out.problems.append(both)
        human, ai = pieces.get(1), pieces.get(2)
        if ai is not None and str(ai.level).upper() == "A-":  # "none" on the second policy's scale
            h, a = _level(human, HUMAN), "A0"
        else:
            h, a = _level(human, HUMAN), _level(ai, AI)
            defined = _ai_as_defined(a, ai, pieces[0].names)
            if defined != a:
                out.lowered += 1
                a = defined
        # conflicting levels for one axis in one message: that axis is unknown
        conflicts = {x for p in pieces.values() if p is not None for x in p.problems}
        bad = {k for x in conflicts for k in error_axes(x)}
        if bad:
            out.conflicting += 1
            out.problems += sorted(conflicts)
            g, h, a = (UNKNOWN if key in bad else v for key, v in zip(LEVEL_KEYS, (g, h, a)))
        if "pull request checkboxes" in pieces[0].source:
            out.boxes += 1
        elif human is None and ai is None and (v := _verification(body)):
            out.legacy += 1
            h = _V_HUMAN.get(v, UNKNOWN)
            a = _V_AI.get(v) or ("A0" if v == "V0" and g == "G0" else UNKNOWN)
        out.generation[g] += 1
        out.human[h] += 1
        out.ai[a] += 1
    return out


def summary_markdown(changes: Changes) -> str:
    """The job summary: how many commits are declared, and how."""
    lines = [f"### AI declarations\n\n{changes.declared} of {changes.commits} commits on the default branch are declared"]
    notes = [f"{changes.boxes} from the ticked questions of merged pull requests"] if changes.boxes else []
    if changes.legacy:
        notes.append(f"{changes.legacy} with the old V0-V3 trailers, mapped conservatively")
    if changes.trailers:
        notes.append(f"{changes.trailers} with \"Key: value\" lines")
    lines[0] += f" ({'; '.join(notes)}).\n" if notes else ".\n"
    how = ["The AI review is counted on " + ("the scale before SIGNOFF.toml version 4 (version = 3), taken over to "
                                             "today's" if changes.version_3 else "today's scale") + "."]
    if changes.corrected:
        how.append(f"{changes.corrected} corrected by [[commits]] entries of SIGNOFF.toml.")
    if changes.lowered:
        how.append(f"{changes.lowered} with an AI review counted lower than declared, as the definitions count it "
                   "(a self-check is A0, a new session of a model that wrote the change A1).")
    if changes.conflicting:
        how.append(f"{changes.conflicting} with conflicting levels, counted as unknown on that axis.")
    lines.append(" ".join(how) + "\n")
    lines.append("| Level | Commits |\n|---|---|")
    for counts in (changes.generation, changes.human, changes.ai):
        for k, n in sorted(counts.items()):
            lines.append(f"| {k} | {n} |")
    return "\n".join(lines) + "\n"
